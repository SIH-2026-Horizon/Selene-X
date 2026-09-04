# Local model registry

Training commands write versioned artifacts here. Docker mounts this directory
at `/models`, and Kubernetes mounts the model PVC at the same path.

```text
model/
  registry.json
  selene_matcher/<version>/weights.pt
  selene_bias/<version>/bias_model.pkl
  iirs_bandweights/<version>/bandweights.npz
  render_residual_prior/<version>/weights.pt
```

`registry.json` records the active version, format, SHA-256, and relative path
for every model. `selene_core.models.LocalModelRegistry` verifies that digest
before returning an artifact to an inference adapter.

The generated registry, manifests, and weights are ignored by Git. Back them
up to the deployment's model object store or persistent volume.
