# Asyntai AI Docs Sync

A Bitrise Step that keeps the [Asyntai](https://asyntai.com) AI chatbot on your website and in your app current with the documentation in your repository. Add one Step to a Workflow. Every page you change is in the chatbot's knowledge base by the end of the build, so your users get the answer that matches the version you just shipped.

Setup guide: https://asyntai.com/documentation/integrations/bitrise/

## Example

```yaml
workflows:
  deploy:
    steps:
    - git-clone: {}
    - asyntai-ai-docs-sync@1:
        inputs:
        - docs_path: docs
        - title_prefix: "Docs / "
```

Read several file types, skip some files, and remove entries whose file is gone:

```yaml
    - asyntai-ai-docs-sync@1:
        inputs:
        - docs_path: site/content
        - file_patterns: "*.md,*.mdx,*.rst"
        - exclude: "drafts/*,CHANGELOG.md"
        - title_prefix: "Docs / "
        - prune: "yes"
```

Before the Step is in the StepLib, use it from Git:

```yaml
    - git::https://github.com/asyntai/bitrise-step-asyntai-ai-docs-sync.git@1.0.0:
        inputs:
        - docs_path: docs
```

## Set up

1. Sign in to Asyntai, open **Settings**, then **API**, and copy your API key.
2. In your Bitrise app, open **Secrets** and add `ASYNTAI_API_KEY` with the key as its value.
3. Add the Step after **Git Clone** and set `docs_path`.

## Inputs

| Input | Default | What it does |
| --- | --- | --- |
| `docs_path` | `docs` | Folder or single file to send. A relative path is read from `$BITRISE_SOURCE_DIR`. |
| `asyntai_api_key` | `$ASYNTAI_API_KEY` | API key. Keep it in a Bitrise Secret. |
| `file_patterns` | `*.md,*.mdx,*.txt` | Comma separated file name patterns to send. |
| `exclude` | | Comma separated patterns to skip. |
| `title_prefix` | | Text put in front of every entry title. |
| `website_id` | | Website to write to. Empty means the first website on the account. |
| `prune` | `no` | `yes` removes entries that carry the title prefix and whose file is gone. Needs `title_prefix`. |
| `dry_run` | `no` | `yes` lists the files and sends nothing. Needs no key. |
| `base_url` | `https://asyntai.com` | API address. Change it only when support asks. |

## Output

| Output | Value |
| --- | --- |
| `ASYNTAI_DOCS_SYNC_SUMMARY` | The last line of the sync, for example `Done. 2 added, 1 updated, 5 unchanged, 0 deleted, 0 skipped.` |

## How it works

Every file becomes one knowledge base entry, and the title comes from the file path. On the next build the Step replaces the old entry with the new text, so a Workflow that runs on every commit does not make duplicates. A file whose text did not change is skipped. Files under 10 characters are skipped.

The Step needs Python 3, which every Bitrise stack has. It installs nothing.

## Run the tests

```bash
bitrise run test
python tests/run_tests.py
```

`bitrise run test` runs the Step in the Bitrise CLI against a stand-in API. `tests/run_tests.py` checks the file layout and the error cases.

## Support

Open an issue: https://github.com/asyntai/bitrise-step-asyntai-ai-docs-sync/issues

## License

MIT
