# Proposed menu validation (not implemented)

Setup currently parses each menu YAML and checks only that its root is a mapping.
Replace that embedded check with a shared, read-only validator. It must never run
actions, connect to SSH, prompt for credentials, or require Docker to be installed.

## Files that would change

- **New `menu_validation.py`:** recursively validate menus and their variable files;
  report the filename and complete label path for every error.
- **`execution_engines/main.py`:** declare required parameter names alongside registered
  action IDs so the validator and executor share the same action definitions.
  Define conditional requirements separately (for example, a remote target needs
  a host, while a local target does not).
- **`main.py`:** validate a selected menu before replacing the current view; show
  actionable validation errors in a dialog. Include UI-owned actions such as
  `configure_remote_credentials` and `lock_remote_credentials` in the definitions.
- **`run-once/run-once`:** invoke `.venv/bin/python menu_validation.py` in the project
  directory before creating the launcher or writing `.setup-complete`. A nonzero
  exit prevents setup from reporting success.
- **New validation tests:** cover current menus and malformed fixtures without
  executing their actions.

## Checks to add

1. Require a mapping at the root, a list for `menu`/`children`, and a nonempty label
   for each entry. Check that `parameters` is a mapping and confirmation fields
   have the expected types.
2. Validate `VariablesFile` exists and contains a variable mapping. Recognize
   informational entries, `special: variables_editor`, and dynamically generated
   backup children as supported menu structures. Also recognize `home_screen`,
   `capture_dialog`, `menu_visibility`, and `moodle_admin_password` UI entries.
3. Check every `action_id` against the engine and UI action registries. Validate
   required parameters, for example `label` and `script_number` for `test_action`,
   and `interface` and `pcap_name` for `replay_pcap`. Keep optional defaults optional.
4. Recursively inspect parameter values for `${VARIABLE}` references, including
   references inside other variables. Reject unknown names and cycles; recognize
   the built-in `GENERATED_SECRET` without generating or displaying a secret.
5. Validate types and constraints after resolving ordinary variables. Report blank
   remote hosts as an action-readiness warning when remote mode is selected, rather
   than rejecting the distributed configuration's unused, blank remote settings.
6. Treat missing capture files or offline archives as readiness warnings, not
   invalid YAML: the supplied training entries are intentionally templates.

Example diagnostics (hypothetical malformed entries, not current failures):

```text
ERROR menus/training.yaml > Host Actions > Host Script 3:
  test_action requires parameter 'script_number'.
ERROR menus/training.yaml > PCAP Replay > Recon > SSH Scan:
  Unknown variable 'PCAP_DIRECTROY'; did you mean 'PCAP_DIRECTORY'?
WARNING menus/training.yaml > PCAP Replay > Recon > SSH Scan:
  Capture is not present; this action is not ready for replay.
```

Legacy `action` entries should be reported separately with an explicit policy;
removing their execution support is a different change from adding validation.
