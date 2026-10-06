# Security Policy

## Supported versions

Motion Studio is pre-1.0 and has no versioned releases yet. Only the latest
commit on the default branch is supported; fixes are not backported.

## Reporting a vulnerability

Please report security issues privately through GitHub's private vulnerability
reporting: open the repository's **Security** tab and choose
**Report a vulnerability**.

Do not open a public issue for a suspected vulnerability, and do not include
secrets or exploit details in public discussions. If private reporting is not
available on the repository, open a public issue that says only that you have a
security report and asks the maintainer for a private channel.

This is a single-maintainer project; expect a best-effort response.

## Secrets

- Motion Studio needs no API keys for its basic workflow and does not read a
  `.env` file.
- Optional provider keys (for example for text-to-speech) belong in your shell
  environment only. Never commit them, and never put them in `meta.json`, run
  records, or project files.
- `.env` files are Git-ignored. If a secret is committed anywhere, rotate it;
  removing the commit is not enough.
- Subprocesses started by the review layer receive a minimal, explicit
  environment rather than your full one (`review/process.py`).

## Third-party dependencies

- The Python code uses only the standard library.
- Rendering runs the HyperFrames CLI through `npx`, pinned per project in
  `package.json`. `npx` downloads and executes code from the npm registry;
  review version bumps before accepting them.
- Templates load GSAP from the jsDelivr CDN at a pinned version.
- HyperFrames agent skills are installed separately by the user and run with
  the agent's full permissions. Review skills before using them; some include
  their own telemetry.
- A composition is HTML and JavaScript executed in a headless browser at render
  time. Only render projects you trust.
