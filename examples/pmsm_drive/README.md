# Example Models

Place your `.slx` files here before running `simvault index`.

After tagging your models with SimVault Description fields, run:

```bash
# From the SimVault/ root:
matlab -batch "run('examples/tag_models_for_simvault.m')"
simvault index examples/pmsm_drive/
```

See `examples/tag_models_for_simvault.m` for the tagging script.
