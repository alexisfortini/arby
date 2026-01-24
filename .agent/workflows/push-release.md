---
description: how to push a new release to git
---

To push a new release to Git using the automated script:

1. Open your terminal in the project root.
2. Run the script with an optional commit message:
   ```bash
   ./push_release.sh "Your commit message here"
   ```
   *If you omit the message, it will default to "Update".*

3. The script will automatically:
   - Stage all changes (`git add .`)
   - Generate a changelog summary
   - Commit and push to your current branch.
