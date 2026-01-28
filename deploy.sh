#!/bin/bash
# Arby Deploy Script
# This script builds the Docker image and deploys it to Cloud Run.

# Run source ../.venv/bin/activate to start the virtual environment
# Run ./deploy.sh gen-lang-client-0397594216 to deploy local changes to website

if [ -z "$1" ]; then
  echo "Usage: ./deploy.sh [PROJECT_ID]"
  exit 1
fi

PROJECT_ID=$1
REGION="us-central1"
REPO_NAME="arby"
IMAGE_NAME="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/arby-app:latest"
BUCKET_NAME="arby-state-$PROJECT_ID"

# --- Optional Data Sync ---
if [ -f "./sync_data.sh" ]; then
    read -p "🔄 Would you like to upload your local DATA (state) to GCP before deploying? (y/n): " SYNC
    if [[ "$SYNC" == "y"* ]]; then
        bash ./sync_data.sh push
    fi
fi

echo "--- Building and Pushing Image to Artifact Registry ---"
echo "--- Checking Artifact Registry ---"
# Check if the repository already exists
REPO_EXISTS=$(gcloud artifacts repositories describe $REPO_NAME --location=$REGION --format="value(name)" 2>/dev/null)

if [ -z "$REPO_EXISTS" ]; then
    echo "Creating repository $REPO_NAME..."
    gcloud artifacts repositories create $REPO_NAME \
        --repository-format=docker \
        --location=$REGION \
        --description="Arby Docker Repository"
else
    echo "✅ Repository $REPO_NAME already exists."
fi

gcloud builds submit --tag $IMAGE_NAME .

echo "--- Deploying to Cloud Run ---"
gcloud run deploy arby \
  --image $IMAGE_NAME \
  --region $REGION \
  --platform managed \
  --allow-unauthenticated \
  --add-volume=name=state-vol,type=cloud-storage,bucket=$BUCKET_NAME \
  --add-volume-mount=volume=state-vol,mount-path=/app/state

echo "--- Deployment Complete ---"
gcloud run services describe arby --region $REGION --format='value(status.url)'
