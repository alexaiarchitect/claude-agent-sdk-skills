# `stale_runner` fixture — an eval suite a version behind

`evals/runner/agent_sdk_evals/VERSION` is `0.0.1` and `evals/eval_config.json`
declares `"runner_version": "0.0.1"`, while the plugin ships a newer runner.

What that produces:

* `DEP001` — the copy is older than the plugin's runner.
* `CFG050` — the config's `runner_version` disagrees with the plugin.
* `install_runner.py` refuses without `--upgrade`, and with it shows a diff.

Do not upgrade this fixture. Being behind is the whole of its job.
