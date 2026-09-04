# Kubernetes model workflow

1. Build and publish `infra/docker/Dockerfile.training` as your trainer image.
2. Replace the placeholder Hugging Face repository IDs in
   `dataset-config.yaml` and `training-job.yaml`.
3. Create an optional `huggingface-token` Secret with key `token` for private
   datasets.
4. Apply `model-pvc.yaml`, then run one training Job per model configuration.
5. Mount the same model PVC read-only into workers with
   `worker-model-volume-patch.yaml`.

The example Job trains `selene_matcher`. To train another artifact, change the
config path, dataset ID, job name, and version:

```text
/workspace/train/configs/selene_bias.json
/workspace/train/configs/iirs_bandweights.json
/workspace/train/configs/render_residual_prior.json
```

All trainers publish into `/models` and update `/models/registry.json`. Do not
run multiple training Jobs against a `ReadWriteOnce` volume unless the storage
class and scheduler place them on the same node. Sequential Jobs are the safe
default.
