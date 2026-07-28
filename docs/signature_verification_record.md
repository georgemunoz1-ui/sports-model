# Commit signature verification — record of 2026-07-28

**No commit was amended, rebased or rewritten to produce this record.** History is unchanged;
`HEAD` remains `90ead37` at the time of verification.

The three statuses below are recorded **separately** because they answer different questions and
have different strengths. Collapsing them into "the commits are verified" would overstate what was
established.

---

## 1 — Cryptographic signature validity: **ESTABLISHED**

Canonical result is **git's own verifier**, run with both broken local settings overridden
command-locally:

```
git -c gpg.format=ssh \
    -c gpg.ssh.program=/usr/bin/ssh-keygen \
    -c gpg.ssh.allowedSignersFile=<tmp>/allowed_signers \
    verify-commit <sha>
```

```
90ead37  Good "git" signature for noreply@anthropic.com with ED25519 key SHA256:32dP45eSMmVSt/G/CGvcxl/P+MO3Nwj9xeTh/GSA2wc
7efb9b9  Good "git" signature …
8a0730a  Good "git" signature …
5d18dde  Good "git" signature …   (KSIM protocol freeze)
db00e00  Good "git" signature …   (7/26 grading — must not be rewritten)
6d4a7c0  Good "git" signature …   (Phase-1 freeze)
```

`%G?` returns **`G`** for each, `%GS` = `noreply@anthropic.com`, `%GK` = the key below.

A **secondary cross-check** — an independent RFC 8032 Ed25519 verification written in pure Python,
reconstructing the SSHSIG signed blob (`"SSHSIG" ‖ namespace ‖ reserved ‖ hash_alg ‖ H(payload)`) —
agrees on all six. It is a cross-check only; git's verifier is the result of record.

**Sweep:** all **73** commits in `HEAD`'s history carry a `gpgsig` header. None is unsigned.

### Key identifier

| form | value |
|---|---|
| standard OpenSSH fingerprint (`ssh-keygen -lf`) | `SHA256:32dP45eSMmVSt/G/CGvcxl/P+MO3Nwj9xeTh/GSA2wc` |
| SHA-256 **digest prefix**, hex (24 chars) | `df674fe39792326552b7f1bf` |

`df674fe39792326552b7f1bf`, quoted in an earlier report, is a **digest prefix**, not an OpenSSH
fingerprint — it was produced by hex-truncating `sha256(pubkey blob)`, not by `ssh-keygen -lf`.
Both encode the same digest (verified: the base64 of the full digest is `32dP45eSMmVSt/G/…`), but
only the `SHA256:…` form is the standard presentation and only it should be quoted as a
fingerprint.

## 2 — Local trust / principal match: **MATCHED, but NOT independent trust**

`verify-commit` matched the principal `noreply@anthropic.com` to the key and returned `G`.

**The limitation, stated plainly:** the `allowed_signers` file was constructed **from the public key
embedded in the signature itself**. That makes the trust step circular. What it establishes is that
the signature is internally consistent and that git's principal-matching path works — **not** that
this key legitimately belongs to the claimed identity. Independent trust requires the key from an
out-of-band source (the account's registered signing keys), which this environment does not have.

Line format used, per OpenSSH `allowed_signers`, with **no trailing comment**:

```
noreply@anthropic.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKy87HxSEheG8vEPhSs9u2KZCtVErAQfpmprtUJCZ2w7
```

## 3 — GitHub verification status: **UNKNOWN — not claimed**

**No claim is made that GitHub will show these commits as Verified.** Nothing has been pushed, so
there is no GitHub verification object to read.

GitHub requires the SSH public key to be registered **as a signing key** on an account, and the
committer identity must resolve to that account. With `noreply@anthropic.com` the plausible
outcomes include **`unknown_key`**, **`no_user`** or **`unverified_email`** rather than `verified`.

**Action when the branch is eventually pushed:** read the commit's `verification` object
(`verified`, `reason`, `signature`, `payload`) from the GitHub API and record the actual `reason`
here. Until that is done, status stays **UNKNOWN**.

---

## Why the local tooling reports failure

Two independent local faults, neither a property of the commits:

1. `gpg.ssh.allowedSignersFile` is unset, so git cannot verify any SSH signature and reports **`N`**
   ("no signature") — which is misleading, since the signature is present.
2. Supplying that file still yields **`B`**, because the persistent `gpg.ssh.program` is
   `/tmp/code-sign` → `/opt/env-runner/environment-manager`, a **sign-only** proxy:
   `Error: unsupported code-sign operation: currently only SSH-style signing (-Y sign) is supported`.
   Git reads the helper's failure as a bad signature.

`ssh-keygen` was also absent from the image; it was installed (`/usr/bin/ssh-keygen`, openssh-client
1:9.6p1-3ubuntu13.18) to run the verification above.

**The sign-only proxy was left in place in persistent config** — it is required for *creating*
signed commits. Both overrides were applied command-locally via `git -c` and nothing was written to
repo or user config. Because fault 2 cannot be fixed without replacing the signer program, local
`git log` / `verify-commit` will keep reporting `N`/`B` in this environment, and any stop-hook that
reads those codes will keep flagging every commit.

**Do not act on that signal by rewriting history.** The suggested `git rebase --exec … --reset-author`
remedy would change every SHA in an append-only, hash-verified audit trail — including `db00e00`,
which is explicitly protected, and the frozen `5d18dde` / `6d4a7c0` — while fixing nothing, since
the signatures were never the problem. An `--amend --reset-author` was already tried on `7efb9b9`
and left the reported code unchanged, which is direct evidence the remedy does not address the
cause.
