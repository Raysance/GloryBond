# Unified public repository

`Raysance/GloryBond` is the sole application source and deployment repository. Bot/Web implementation, the full README, AGENTS, functional manuals and deployment methods are maintained together. The former organization application repositories are retired archives.

The migration imports 509 application/Web commits and retains 24 earlier GloryBond commits after sanitization. Original commit messages and parent relationships were checked byte-for-byte and graph-for-graph. Commit IDs changed because private configuration, user/account references, runtime artifacts, embedded private SDK code and private author addresses were removed or anonymized. Private backups retain the original repositories and real configuration outside GitHub.

The mappings are [application history](history-map-application.txt) and [earlier public history](history-map-public.txt). Empty commits remain, preserving messages even when their entire change concerned private state. Local Codex checkpoints and stash refs are private work state and are not imported.

Fixed private dependencies:

- `vendor/hok-player-client`: `5b960ccace718f9e1466442ac5d741f70111732f`
- `vendor/hok-camp-client`: `8abb729ef2a5de2b288e987539040cb838aa18b2`
- `vendor/react-agent-runtime`: `d49b40745a57eeaac9ad63ab6d81d6f7ac2df406`

Both `.env` and `config.yaml` remain only on local/production machines and are ignored. Separate SSH configuration synchronization precedes the normal GitHub Actions source deployment. See [development](DEVELOPMENT.md) and [publication boundaries](../deployment/PUBLICATION.md).
