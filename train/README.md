# Model training

This package contains one trainer for every model named in the SELENE-XR
technical specification:

- `selene_matcher`: five-group dense flow and uncertainty model.
- `selene_bias`: gradient-boosted sub-pixel bias correction.
- `iirs_bandweights`: sum-normalized learned IIRS collapse weights.
- `render_residual_prior`: optional per-pixel render-error CNN.

Install locally with:

```bash
python -m pip install -e './packages/selene_core[learned]' -e ./train
```

Run a model with a local NPZ split:

```bash
selene-train train \
  --config train/configs/selene_matcher.json \
  --dataset data/selene_matcher \
  --version dev-001
```

Run against Hugging Face:

```bash
export HF_TOKEN=your_token_if_private
selene-train train \
  --config train/configs/selene_matcher.json \
  --dataset hf://your-account/selene-xr-matcher \
  --version matcher-2026-08-29
```

The command writes the weights, run manifest, metrics, and active registry entry
under `model/`. Use `--no-activate` to publish without changing the active local
version.

Load an active artifact from application or worker code:

```python
from selene_core import load_local_model

loaded = load_local_model("selene_matcher", device="cuda")
predicted_flow, log_variance = loaded.value(source, reference, prior_flow)
```

Set `SXR_MODEL_ROOT=./model` outside a container. Docker and Kubernetes use the
default mounted path `/models`.

The included `selene_matcher` is a compact grouped dense-flow baseline that
makes the data, artifact, and deployment pipeline executable. The research
specification's full LoFTR/RoMa-lineage architecture, DDP curriculum, and
self-supervised adaptation remain a later model-quality iteration; they can
replace this architecture without changing the dataset or registry contracts.
