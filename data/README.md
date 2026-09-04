# Dataset metadata and local cache

The repository tracks dataset contracts and Hugging Face repository IDs here,
but never commits mission imagery or generated training arrays. Copy
`datasets.example.json` to an ignored `datasets.json` and replace the repository
IDs after uploading each dataset.

Training accepts either `hf://owner/repository`, a directory containing
`train.npz`, or a direct NPZ path. Hugging Face access uses `HF_TOKEN` when the
repository is private.

## Required fields

| Model | Arrays in each split |
| --- | --- |
| `selene_matcher` | `source [N,5,H,W]`, `reference [N,5,H,W]`, `prior_flow [N,2,H,W]`, `flow [N,2,H,W]`, `valid_mask [N,1,H,W]` |
| `selene_bias` | `features [N,F]`, `target_bias [N,1 or 2]` |
| `iirs_bandweights` | `radiance [N,B,H,W]`, `target [N,1,H,W]`, `valid_mask [N,1,H,W]` |
| `render_residual_prior` | `render [N,1,H,W]`, `source [N,1,H,W]`, `angles [N,A,H,W]`, `target_error [N,1,H,W]`, `valid_mask [N,1,H,W]` |

Hugging Face datasets must expose the same field names as array-valued
features. Local NPZ files must use `float32` arrays and share the same first
dimension.
