---
name: deploy
description: Prepare, version bump, commit, push, and deploy a new release of Arby to GitHub and Google Cloud Run. Use whenever the user asks to "push and deploy", "deploy", "create a release", or "ship to production".
metadata:
  author: arby-team
  version: "1.0.0"
---

# Arby Push & Deploy Runbook

This skill automates releasing and deploying Arby to GitHub and Google Cloud Run.

## Release Process Overview

1. **Version Bump**:
   - Locate `inject_version()` in `app/web/server.py`.
   - Update `app_version="vX.X.X"` to the target version (or increment patch version, e.g., `v1.0.17` -> `v1.0.18`).

2. **Verify Changes**:
   - Review modified files with `git status`.
   - Ensure clean syntax, no stray console logs or leftover temporary files.

3. **Stage & Commit**:
   - Stage all relevant changes:
     ```bash
     git add -A
     ```
   - Commit using standard Arby release commit format:
     - Standard Release: `vX.X.X Release`
     - Patch / Bug Fixes: `vX.X.X Patch Release`
     Example:
     ```bash
     git commit -m "v1.0.17 Patch Release"
     ```

4. **Push to Remote**:
   - Push main branch to GitHub:
     ```bash
     git push origin main
     ```

5. **Deploy to Google Cloud Run**:
   - GCP Project ID: `gen-lang-client-0397594216`
   - Region: `us-central1`
   - Service: `arby`
   - Image: `us-central1-docker.pkg.dev/gen-lang-client-0397594216/arby/arby-app:latest`
   - Bucket: `arby-state-gen-lang-client-0397594216`
   - Run deployment script (answer `n` to data push unless local state sync is explicitly requested):
     ```bash
     echo "n" | ./deploy.sh gen-lang-client-0397594216
     ```
   - Alternatively, execute the Cloud Build & Cloud Run deploy commands directly:
     ```bash
     gcloud builds submit --tag us-central1-docker.pkg.dev/gen-lang-client-0397594216/arby/arby-app:latest .
     gcloud run deploy arby \
       --image us-central1-docker.pkg.dev/gen-lang-client-0397594216/arby/arby-app:latest \
       --region us-central1 \
       --platform managed \
       --allow-unauthenticated \
       --add-volume=name=state-vol,type=cloud-storage,bucket=arby-state-gen-lang-client-0397594216 \
       --add-volume-mount=volume=state-vol,mount-path=/app/state \
       --memory=512Mi \
       --cpu=1
     ```

6. **Post-Deployment Verification**:
   - Fetch the service URL:
     ```bash
     gcloud run services describe arby --region us-central1 --format='value(status.url)'
     ```
   - Verify health endpoint:
     ```bash
     curl -s <service-url>/health
     ```
   - Confirm live website displays the new version tag.
