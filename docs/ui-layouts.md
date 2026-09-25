# Preserved interface layouts

The original **Projects / Overview** interface is preserved on the local Git
branch `snapshot/project-first-ui` at commit
`008cd97429c611d1ea176a4e2ad1208c0a7106a9`. Its 13 frontend files match the verified
earlier source-distribution copy. The snapshot pairs that interface with the
current public backend, which retains the project-scoped API routes.

Creating this fallback did not switch branches, restore files, or modify the
normal Git index. The active working tree continues to contain the newer **Chat**,
optional-project, and **Search Settings** interface. The snapshot is local only;
it has not been pushed or published. Private notes, credentials, runtime databases,
compiled desktop applications, dependencies and generated build outputs are excluded.

## Restore the Projects / Overview frontend deliberately

Review and preserve any uncommitted frontend work first. The restore command
below replaces frontend source files with the saved layout; it is not a preview.
It does not switch branches or roll back backend code or saved workspace data.

```text
git status --short -- frontend
git diff -- frontend
git restore --source snapshot/project-first-ui -- frontend
```

For the Docker application, rebuild its image and restart/reuse the managed
service through the normal launcher:

```text
docker build -t labcat:0.1.0.dev0 .
./labcat.sh start --no-open
```

On Windows, use `labcat.cmd start -NoOpen`. The launcher prints the running
address; open it in a browser or launch the native application. The named workspace
volume is retained. Do not remove volumes to change an interface layout.

For a native Python development service, rebuild the frontend assets instead:

```text
npm ci --prefix frontend
npm run build --prefix frontend
```

Refresh the UI after rebuilding. The old layout does not expose the newer
standalone-chat and editable-settings screens; their backend records remain
stored. Existing projects remain accessible through the preserved interface.
