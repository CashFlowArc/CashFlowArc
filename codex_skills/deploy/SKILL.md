---
name: deploy
description: Commit current repository changes, push them to the configured git remote, and verify the live deployment on cashflowarc.com after the push. Use when the user says "deploy" or clearly wants a commit-and-push workflow with post-deploy live-site verification.
---

# Deploy

Treat `deploy` as an execution workflow, not a planning request.

## Workflow

1. Inspect the current git worktree and confirm what will be deployed.
2. Stage only the intended changes.
3. Create a focused commit message that matches the change.
4. Push the current branch to the configured remote.
5. Verify the live deployment on `https://cashflowarc.com`.

## Verification

After the push, verify the deployment from the live site.

- Check that `https://cashflowarc.com` responds successfully.
- Check the most relevant route for the change when one exists, such as `/`, `/gex`, or `/option-chain`.
- Confirm the deployed page contains the expected change at a basic content level.
- Report any mismatch between the pushed code and the live response.

## Constraints

- Do not say a deploy succeeded until the push and the live-site verification both succeeded.
- If push succeeds but live verification fails, report that as a partial deploy result.
- Prefer concise reporting: commit SHA, commit message, push result, and verification result.
- If the change affects a specific page, choose that page as the primary verification target instead of only checking the homepage.
