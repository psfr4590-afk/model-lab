"""
model.py — Llama-style decoder-only transformer.

Sized for GTX 1650 (4GB VRAM):
  - Default: 117M params (GPT-2 small equivalent)
  - Fits in fp16 with batch=1 + gradient accumulation
  - Architecture matches llama.cpp's 'llama' arch for GGUF compat

Components:
  RMSNorm, RoPE, SwiGLU FFN, causal self-attention
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class ModelConfig:
    # Architecture
    vocab_size:   int   = 32000
    seq_len:      int   = 1024
    n_layers:     int   = 12
    n_heads:      int   = 12
    n_kv_heads:   int   = 12      # set < n_heads for grouped-query attention
    d_model:      int   = 768
    d_ffn:        int   = 2048    # typically ~2.67 * d_model for SwiGLU
    dropout:      float = 0.0
    bias:         bool  = False
    norm_eps:     float = 1e-5
    rope_theta:   float = 10000.0

    # Presets — call ModelConfig.from_preset("117M")
    @classmethod
    def from_preset(cls, name: str) -> "ModelConfig":
        presets = {
            # ~117M params — fits GTX 1650 comfortably
            "117M": cls(n_layers=12, n_heads=12, n_kv_heads=12,
                        d_model=768,  d_ffn=2048),
            # ~360M params — tight on 4GB, needs batch=1, grad_accum>=16
            "360M": cls(n_layers=24, n_heads=16, n_kv_heads=16,
                        d_model=1024, d_ffn=2816),
            # ~85M params — fastest iteration
            "85M":  cls(n_layers=10, n_heads=10, n_kv_heads=10,
                        d_model=640,  d_ffn=1728),
        }
        if name not in presets:
            raise ValueError(f"Unknown preset '{name}'. Options: {list(presets)}")
        return presets[name]

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def param_count(self) -> int:
        """Estimate parameter count."""
        embed    = self.vocab_size * self.d_model
        attn     = self.n_layers * (
            self.d_model * self.d_model +                           # Q
            2 * (self.d_model // self.n_heads * self.n_kv_heads) * self.d_model +  # K, V
            self.d_model * self.d_model                             # O
        )
        ffn      = self.n_layers * (3 * self.d_model * self.d_ffn)  # SwiGLU has 3 matrices
        norms    = self.n_layers * 2 * self.d_model + self.d_model
        lm_head  = self.vocab_size * self.d_model
        return embed + attn + ffn + norms + lm_head


# ── RMSNorm ──────────────────────────────────────────────────────────────────

class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-5):
        super().__init__()
        self.eps    = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        norm = x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
        return norm * self.weight


# ── RoPE ─────────────────────────────────────────────────────────────────────

def precompute_freqs(dim: int, seq_len: int, theta: float = 10000.0,
                     device: torch.device = None) -> tuple[torch.Tensor, torch.Tensor]:
    freqs = 1.0 / (theta ** (torch.arange(0, dim, 2, device=device).float() / dim))
    t     = torch.arange(seq_len, device=device)
    freqs = torch.outer(t, freqs)
    cos   = torch.cos(freqs)
    sin   = torch.sin(freqs)
    return cos, sin


def apply_rope(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    # x: (B, T, n_heads, head_dim)
    # cos/sin: (T, head_dim//2) from precompute_freqs
    B, T, H, D = x.shape
    half = D // 2
    x1 = x[..., :half]           # (B, T, H, half)
    x2 = x[..., half:]           # (B, T, H, half)
    # cos/sin already half-dim; reshape for broadcast: (1, T, 1, half)
    c = cos[:T, :half].unsqueeze(0).unsqueeze(2)
    s = sin[:T, :half].unsqueeze(0).unsqueeze(2)
    # Apply rotation to each half independently then concat
    out1 = x1 * c - x2 * s
    out2 = x1 * s + x2 * c
    return torch.cat([out1, out2], dim=-1)


# ── SwiGLU FFN ───────────────────────────────────────────────────────────────

class SwiGLU(nn.Module):
    def __init__(self, d_model: int, d_ffn: int, bias: bool = False):
        super().__init__()
        self.gate = nn.Linear(d_model, d_ffn, bias=bias)
        self.up   = nn.Linear(d_model, d_ffn, bias=bias)
        self.down = nn.Linear(d_ffn,   d_model, bias=bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.down(F.silu(self.gate(x)) * self.up(x))


# ── Attention ─────────────────────────────────────────────────────────────────

class CausalSelfAttention(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        assert cfg.d_model % cfg.n_heads == 0
        self.n_heads    = cfg.n_heads
        self.n_kv_heads = cfg.n_kv_heads
        self.head_dim   = cfg.d_model // cfg.n_heads
        self.n_rep      = cfg.n_heads // cfg.n_kv_heads  # for GQA repeat

        self.q_proj  = nn.Linear(cfg.d_model, cfg.n_heads    * self.head_dim, bias=cfg.bias)
        self.k_proj  = nn.Linear(cfg.d_model, cfg.n_kv_heads * self.head_dim, bias=cfg.bias)
        self.v_proj  = nn.Linear(cfg.d_model, cfg.n_kv_heads * self.head_dim, bias=cfg.bias)
        self.o_proj  = nn.Linear(cfg.d_model, cfg.d_model,                    bias=cfg.bias)
        self.dropout = cfg.dropout

    def forward(self, x: torch.Tensor, cos: torch.Tensor,
                sin: torch.Tensor, mask: Optional[torch.Tensor] = None) -> torch.Tensor:
        B, T, C = x.shape
        H, KVH, D = self.n_heads, self.n_kv_heads, self.head_dim

        q = self.q_proj(x).view(B, T, H,   D)
        k = self.k_proj(x).view(B, T, KVH, D)
        v = self.v_proj(x).view(B, T, KVH, D)

        q = apply_rope(q, cos, sin)
        k = apply_rope(k, cos, sin)

        # GQA: repeat k,v to match n_heads
        if self.n_rep > 1:
            k = k.repeat_interleave(self.n_rep, dim=2)
            v = v.repeat_interleave(self.n_rep, dim=2)

        # (B, H, T, D)
        q = q.transpose(1, 2)
        k = k.transpose(1, 2)
        v = v.transpose(1, 2)

        # Flash attention if available, else manual
        if hasattr(F, "scaled_dot_product_attention"):
            out = F.scaled_dot_product_attention(
                q, k, v,
                attn_mask=None,
                dropout_p=self.dropout if self.training else 0.0,
                is_causal=True,
            )
        else:
            scale = 1.0 / math.sqrt(D)
            att   = (q @ k.transpose(-2, -1)) * scale
            att   = att.masked_fill(
                torch.triu(torch.ones(T, T, device=x.device), diagonal=1).bool(), float("-inf")
            )
            att = F.softmax(att, dim=-1)
            att = F.dropout(att, p=self.dropout, training=self.training)
            out = att @ v

        out = out.transpose(1, 2).contiguous().view(B, T, C)
        return self.o_proj(out)


# ── Transformer Block ─────────────────────────────────────────────────────────

class Block(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.norm1 = RMSNorm(cfg.d_model, cfg.norm_eps)
        self.attn  = CausalSelfAttention(cfg)
        self.norm2 = RMSNorm(cfg.d_model, cfg.norm_eps)
        self.ffn   = SwiGLU(cfg.d_model, cfg.d_ffn, cfg.bias)

    def forward(self, x: torch.Tensor, cos: torch.Tensor,
                sin: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(self.norm1(x), cos, sin)
        x = x + self.ffn(self.norm2(x))
        return x


# ── Full Model ────────────────────────────────────────────────────────────────

class LlamaModel(nn.Module):
    def __init__(self, cfg: ModelConfig):
        super().__init__()
        self.cfg = cfg

        self.embed   = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.drop    = nn.Dropout(cfg.dropout)
        self.blocks  = nn.ModuleList([Block(cfg) for _ in range(cfg.n_layers)])
        self.norm    = RMSNorm(cfg.d_model, cfg.norm_eps)
        self.lm_head = nn.Linear(cfg.d_model, cfg.vocab_size, bias=False)

        # Weight tying
        self.lm_head.weight = self.embed.weight

        # RoPE buffers (pre-computed, not parameters)
        cos, sin = precompute_freqs(cfg.d_model // cfg.n_heads, cfg.seq_len, cfg.rope_theta)
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)

        self.apply(self._init_weights)
        # Scale residual projections
        for name, p in self.named_parameters():
            if name.endswith(("o_proj.weight", "down.weight")):
                nn.init.normal_(p, mean=0.0, std=0.02 / math.sqrt(2 * cfg.n_layers))

    def _init_weights(self, module: nn.Module):
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if module.bias is not None:
                nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(self, idx: torch.Tensor,
                targets: Optional[torch.Tensor] = None) -> tuple[torch.Tensor, Optional[torch.Tensor]]:
        B, T = idx.shape
        assert T <= self.cfg.seq_len, f"Sequence length {T} > max {self.cfg.seq_len}"

        cos = self.rope_cos[:T]
        sin = self.rope_sin[:T]

        x = self.drop(self.embed(idx))
        for block in self.blocks:
            x = block(x, cos, sin)
        x = self.norm(x)

        if targets is not None:
            logits = self.lm_head(x)
            loss   = F.cross_entropy(logits.view(-1, logits.size(-1)),
                                     targets.view(-1), ignore_index=-1)
            return logits, loss

        # Inference: only compute last token
        logits = self.lm_head(x[:, [-1], :])
        return logits, None

    @torch.no_grad()
    def generate(self, idx: torch.Tensor, max_new_tokens: int,
                 temperature: float = 1.0, top_k: int = 50) -> torch.Tensor:
        for _ in range(max_new_tokens):
            idx_cond = idx if idx.size(1) <= self.cfg.seq_len else idx[:, -self.cfg.seq_len:]
            logits, _ = self(idx_cond)
            logits = logits[:, -1, :] / temperature
            if top_k is not None:
                v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                logits[logits < v[:, [-1]]] = float("-inf")
            probs  = F.softmax(logits, dim=-1)
            next_t = torch.multinomial(probs, num_samples=1)
            idx    = torch.cat((idx, next_t), dim=1)
        return idx

    def param_count(self) -> int:
        return sum(p.numel() for p in self.parameters())
