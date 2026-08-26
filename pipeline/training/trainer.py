"""
train.py — Pretraining loop.

Features:
  - fp16 AMP (torch.cuda.amp) — essential for GTX 1650 4GB
  - Gradient accumulation — simulate large batches
  - Cosine LR schedule with linear warmup
  - Checkpoint every N steps + best-val checkpoint
  - Eval on val shards every N steps
  - Resume from latest checkpoint
  - Gradient clipping
  - Loss/perplexity logging to file + console
  - Optional sample generation every N steps to sanity-check output

Config lives in pipeline_config.yaml under the 'train' key.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn
import numpy as np

from pipeline.trainer.model import LlamaModel, ModelConfig
from pipeline.shardwriter.shard_writer import ShardDataLoader

log = logging.getLogger("trainer")


# ── LR Schedule ──────────────────────────────────────────────────────────────

def cosine_lr(step: int, warmup_steps: int, lr_max: float,
              lr_min: float, total_steps: int) -> float:
    if step < warmup_steps:
        return lr_max * step / max(warmup_steps, 1)
    if step > total_steps:
        return lr_min
    progress = (step - warmup_steps) / max(total_steps - warmup_steps, 1)
    return lr_min + 0.5 * (lr_max - lr_min) * (1 + math.cos(math.pi * progress))


# ── Checkpoint helpers ────────────────────────────────────────────────────────

def save_checkpoint(model: LlamaModel, optimizer: torch.optim.Optimizer,
                    scaler: torch.amp.GradScaler,
                    step: int, val_loss: float,
                    cfg: dict, out_dir: Path, tag: str = ""):
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"ckpt_{tag}_{step:07d}.pt" if tag else f"ckpt_{step:07d}.pt"
    path = out_dir / name
    payload = {
        "step":        step,
        "model":       model.state_dict(),
        "optimizer":   optimizer.state_dict(),
        "scaler":      scaler.state_dict(),
        "val_loss":    val_loss,
        "model_cfg":   model.cfg.to_dict(),
        "train_cfg":   cfg,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, tmp)
    os.replace(tmp, path)
    log.info(f"Checkpoint saved atomically: {path} (step={step} val_loss={val_loss:.4f})")
    return path


def load_checkpoint(path: Path, model: LlamaModel,
                    optimizer: Optional[torch.optim.Optimizer] = None,
                    scaler: Optional[torch.amp.GradScaler] = None,
                    device: torch.device = None) -> int:
    if not path.exists() or path.stat().st_size < 1024:
        raise RuntimeError(f"Checkpoint missing or obviously truncated: {path}")
    try:
        ckpt = torch.load(path, map_location=device or "cpu")
    except Exception as exc:
        raise RuntimeError(f"Checkpoint is unreadable/corrupt: {path}: {exc}") from exc
    if not isinstance(ckpt, dict) or "model" not in ckpt or "step" not in ckpt:
        raise RuntimeError(f"Checkpoint schema invalid: {path}")
    model.load_state_dict(ckpt["model"])
    if optimizer and "optimizer" in ckpt:
        optimizer.load_state_dict(ckpt["optimizer"])
    if scaler and "scaler" in ckpt:
        scaler.load_state_dict(ckpt["scaler"])
    step = ckpt.get("step", 0)
    log.info(f"Resumed from {path} at step {step} (val_loss={ckpt.get('val_loss', '?'):.4f})")
    return step


def latest_checkpoint(ckpt_dir: Path) -> Optional[Path]:
    ckpts = sorted(ckpt_dir.glob("ckpt_*.pt"))
    return ckpts[-1] if ckpts else None


# ── Training loop ─────────────────────────────────────────────────────────────

class Trainer:

    def __init__(self, cfg: dict):
        self.cfg     = cfg
        self.t_cfg   = cfg.get("train", {})
        self.out_dir = Path(cfg.get("pipeline", {}).get("output_dir", "output"))
        self.ckpt_dir = self.out_dir / "checkpoints"
        self.log_path = self.out_dir / "logs" / "train.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._setup_file_logger()

    def _setup_file_logger(self):
        fh  = logging.FileHandler(self.log_path, encoding="utf-8")
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                datefmt="%Y-%m-%dT%H:%M:%S")
        fh.setFormatter(fmt)
        log.addHandler(fh)

    def run(self):
        t_cfg   = self.t_cfg
        device  = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        log.info(f"Training device: {device}")
        if device.type == "cuda":
            log.info(f"  GPU: {torch.cuda.get_device_name(0)}")
            log.info(f"  VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

        # ── Model ────────────────────────────────────────────────────────────
        preset    = t_cfg.get("model_preset", "117M")
        model_cfg = ModelConfig.from_preset(preset)
        model_cfg.vocab_size = t_cfg.get("vocab_size", 32000)
        model_cfg.seq_len    = t_cfg.get("seq_len", 1024)
        model_cfg.dropout    = t_cfg.get("dropout", 0.0)

        model = LlamaModel(model_cfg).to(device)
        params = model.param_count()
        log.info(f"Model: {preset} | params={params/1e6:.1f}M")

        # ── Optimizer ────────────────────────────────────────────────────────
        lr_max      = float(t_cfg.get("lr_max", 3e-4))
        lr_min      = float(t_cfg.get("lr_min", 3e-5))
        weight_decay = float(t_cfg.get("weight_decay", 0.1))
        # Separate decay/no-decay params (no decay on norms, biases, embeddings)
        decay, no_decay = [], []
        for name, p in model.named_parameters():
            if not p.requires_grad:
                continue
            if p.dim() < 2 or "norm" in name or "bias" in name or "embed" in name:
                no_decay.append(p)
            else:
                decay.append(p)
        optimizer = torch.optim.AdamW(
            [{"params": decay,    "weight_decay": weight_decay},
             {"params": no_decay, "weight_decay": 0.0}],
            lr=lr_max, betas=(0.9, 0.95), fused=False,
        )

        # ── AMP scaler ───────────────────────────────────────────────────────
        scaler = torch.amp.GradScaler("cuda", enabled=(device.type == "cuda"))

        # ── Training hyperparams ─────────────────────────────────────────────
        total_steps    = int(t_cfg.get("total_steps", 100_000))
        warmup_steps   = int(t_cfg.get("warmup_steps", 2_000))
        batch_size     = int(t_cfg.get("batch_size", 1))        # micro-batch
        grad_accum     = int(t_cfg.get("grad_accum_steps", 16)) # effective batch = batch*grad_accum
        grad_clip      = float(t_cfg.get("grad_clip", 1.0))
        eval_every     = int(t_cfg.get("eval_every_steps", 500))
        ckpt_every     = int(t_cfg.get("checkpoint_every_steps", 1000))
        gen_every      = int(t_cfg.get("generate_every_steps", 2000))
        eval_batches   = int(t_cfg.get("eval_batches", 20))
        seq_len        = model_cfg.seq_len
        shard_dir      = Path(self.t_cfg.get("shard_dir", "output/shards"))
        dtype          = np.uint16

        eff_batch = batch_size * grad_accum
        log.info(f"Effective batch size: {eff_batch} tokens × {seq_len} = "
                 f"{eff_batch * seq_len:,} tokens/step")
        log.info(f"Total steps: {total_steps} | warmup: {warmup_steps} | "
                 f"eval every: {eval_every} | ckpt every: {ckpt_every}")

        # ── Data loaders ─────────────────────────────────────────────────────
        train_loader = ShardDataLoader(shard_dir, "train", seq_len, dtype=dtype)
        val_loader   = ShardDataLoader(shard_dir, "val",   seq_len, dtype=dtype)

        # ── Resume ───────────────────────────────────────────────────────────
        start_step = 0
        best_val   = float("inf")
        resume     = t_cfg.get("resume", True)
        if resume:
            ckpt = latest_checkpoint(self.ckpt_dir)
            if ckpt:
                start_step = load_checkpoint(ckpt, model, optimizer, scaler, device)

        # ── Tokenizer for generation samples ─────────────────────────────────
        tok_path = self.out_dir / "tokenizer" / "tokenizer.json"
        tokenizer = None
        if gen_every > 0 and tok_path.exists():
            try:
                from tokenizers import Tokenizer
                tokenizer = Tokenizer.from_file(str(tok_path))
                bos_id    = tokenizer.token_to_id("<|bos|>") or 1
            except Exception:
                tokenizer = None

        # ── Log file (JSONL) ─────────────────────────────────────────────────
        metrics_path = self.out_dir / "logs" / "metrics.jsonl"
        metrics_f    = open(metrics_path, "a", encoding="utf-8")

        def log_metric(**kwargs):
            metrics_f.write(json.dumps(kwargs) + "\n")
            metrics_f.flush()

        # ── Training ─────────────────────────────────────────────────────────
        model.train()
        optimizer.zero_grad(set_to_none=True)
        t0      = time.time()
        step    = start_step
        accum_loss = 0.0

        log.info("=" * 60)
        log.info("Training started")
        log.info("=" * 60)

        while step < total_steps:
            # LR update
            lr = cosine_lr(step, warmup_steps, lr_max, lr_min, total_steps)
            for group in optimizer.param_groups:
                group["lr"] = lr

            # Gradient accumulation loop
            for micro in range(grad_accum):
                x, y = train_loader.next_batch(batch_size)
                x, y = x.to(device), y.to(device)

                with torch.amp.autocast(device_type="cuda", enabled=(device.type == "cuda"), dtype=torch.float16):
                    _, loss = model(x, y)
                    loss    = loss / grad_accum

                scaler.scale(loss).backward()
                accum_loss += loss.item()

            # Optimizer step
            scaler.unscale_(optimizer)
            grad_norm = nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad(set_to_none=True)

            step += 1
            train_loss = accum_loss
            accum_loss  = 0.0

            # ── Logging ──────────────────────────────────────────────────────
            if step % 10 == 0:
                dt      = time.time() - t0
                tok_s   = (step - start_step) * eff_batch * seq_len / dt
                ppl     = math.exp(min(train_loss, 20))
                eta_h   = (total_steps - step) * dt / max(step - start_step, 1) / 3600
                log.info(
                    f"step={step:7d}/{total_steps} "
                    f"loss={train_loss:.4f} ppl={ppl:.1f} "
                    f"lr={lr:.2e} gnorm={grad_norm:.3f} "
                    f"tok/s={tok_s:.0f} eta={eta_h:.1f}h"
                )
                log_metric(step=step, train_loss=train_loss, ppl=ppl, lr=lr,
                           grad_norm=float(grad_norm), tokens_per_sec=tok_s)

            # ── Eval ─────────────────────────────────────────────────────────
            if step % eval_every == 0:
                val_loss = self._eval(model, val_loader, device, eval_batches, batch_size)
                val_ppl  = math.exp(min(val_loss, 20))
                log.info(f"[EVAL] step={step} val_loss={val_loss:.4f} val_ppl={val_ppl:.1f}")
                log_metric(step=step, val_loss=val_loss, val_ppl=val_ppl)
                model.train()

                if val_loss < best_val:
                    best_val = val_loss
                    save_checkpoint(model, optimizer, scaler, step, val_loss,
                                    self.t_cfg, self.ckpt_dir, tag="best")

            # ── Checkpoint ───────────────────────────────────────────────────
            if step % ckpt_every == 0:
                # Save latest
                save_checkpoint(model, optimizer, scaler, step,
                                best_val, self.t_cfg, self.ckpt_dir)
                # Prune old checkpoints (keep last 3 + best)
                self._prune_checkpoints(self.ckpt_dir, keep=3)

            # ── Sample generation ─────────────────────────────────────────────
            if gen_every > 0 and step % gen_every == 0 and tokenizer is not None:
                self._generate_sample(model, tokenizer, device,
                                      prompt="The transformer architecture",
                                      max_new=200)
                model.train()

        # Final checkpoint
        val_loss = self._eval(model, val_loader, device, eval_batches * 2, batch_size)
        save_checkpoint(model, optimizer, scaler, step, val_loss,
                        self.t_cfg, self.ckpt_dir, tag="final")
        metrics_f.close()
        log.info(f"Training complete. Final val_loss={val_loss:.4f}")

        return model, step

    @torch.no_grad()
    def _eval(self, model: LlamaModel, loader: ShardDataLoader,
              device: torch.device, n_batches: int, batch_size: int) -> float:
        model.eval()
        losses = []
        for _ in range(n_batches):
            x, y = loader.next_batch(batch_size)
            x, y = x.to(device), y.to(device)
            with torch.amp.autocast(device_type="cuda", enabled=(device.type == "cuda"), dtype=torch.float16):
                _, loss = model(x, y)
            losses.append(loss.item())
        return float(np.mean(losses))

    @torch.no_grad()
    def _generate_sample(self, model: LlamaModel, tokenizer,
                         device: torch.device, prompt: str, max_new: int = 100):
        model.eval()
        bos_id = tokenizer.token_to_id("<|bos|>") or 1
        ids    = [bos_id] + tokenizer.encode(prompt).ids
        idx    = torch.tensor([ids], dtype=torch.long, device=device)
        out    = model.generate(idx, max_new, temperature=0.8, top_k=40)
        text   = tokenizer.decode(out[0].tolist())
        log.info(f"[SAMPLE] {text[:300]!r}")

    def _prune_checkpoints(self, ckpt_dir: Path, keep: int = 3):
        ckpts = sorted(ckpt_dir.glob("ckpt_[0-9]*.pt"))
        for old in ckpts[:-keep]:
            try:
                old.unlink()
                log.debug(f"Pruned checkpoint: {old.name}")
            except Exception:
                pass
