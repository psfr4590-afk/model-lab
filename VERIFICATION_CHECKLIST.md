# Model Lab Verification Checklist

This document is the release verification contract for Model Lab. A passing pytest run alone is not sufficient for release.

## Automated checks runnable in any supported development environment

- Package identity and documentation presence.
- Root launcher existence and project-root discovery.
- Complete navigation surface inventory.
- Screen module existence and application registration.
- Complete pipeline stage inventory.
- Pipeline service validation of stage names.
- Dataset, group, stage, stop, system, and credential API route presence.
- Four credential presets and their environment-variable mappings.
- Credential encryption/decryption implementation and Windows DPAPI path.
- Non-Windows Fernet fallback contract.
- Desktop backend startup uses `--no-browser`.
- Target window geometry is 1760x990 with a usable minimum size.
- Dataset selection navigates to Pipeline.
- Dataset create/ingest controls are wired to services.
- Every pipeline stage has a Run control.
- Pipeline Stop is wired.
- Credential Save/Replace is wired.
- Service-to-API route contracts for dataset, credential, crawler, training, and pipeline operations.
- Secret-literal scan over first-party deliverable files.
- Pytest scope excludes vendor `llama.cpp` tests.
- Required release documentation exists.

## Target-machine checks

These checks are included in `tests/model_lab/test_machine_environment.py` and intentionally skip outside the target environment. They must be executed on the actual Windows installation before release acceptance.

- Windows platform.
- Python 3.11 target runtime.
- Tkinter availability.
- Physical display is at least 1760x990.
- Required executables are on PATH.
- NVIDIA `nvidia-smi` availability when GPU verification is applicable.
- PyTorch CUDA capability is observed rather than assumed.
- `llama.cpp` checkout exists.
- Pipeline doctor succeeds.
- Command Center can start without opening a browser and answers `/api/system`.
- Root desktop launcher is structurally valid.

## Human-visible target-machine smoke checks

These cannot honestly be certified by a headless test runner. The release operator must visibly confirm:

1. `python launch.py` opens the Model Lab desktop window.
2. The window fits the 1760x990 display without manual scaling.
3. Every navigation item opens its corresponding surface.
4. Dataset cards can be selected and selection opens Pipeline.
5. Every pipeline stage's Run control invokes the corresponding operation.
6. Stop visibly reaches the backend and updates state.
7. Credential screen displays the four predefined slots: GitHub, Hugging Face, Google API key, Google CX.
8. Entering a secret and Save/Replace updates its configured state without displaying the secret.
9. Sources, Crawler, Training, Outputs, Logs, System, Configuration, Diagnostics, and Command Center surfaces are usable rather than merely present.
10. Command Center startup does not unexpectedly launch a browser when launched by the desktop application.

## Release rule

No final release claim should be made until automated checks pass, target-machine checks pass, and the human-visible smoke checks above are explicitly recorded as PASS or UNKNOWN.
