#!/bin/bash

# Arby Deploy Script
# This script builds the Docker image and deploys it to Cloud Run.

if [ -z "$1" ]; then
  echo "Usage: ./deploy.sh [PROJECT_ID]"
  exit 1
fi

PROJECT_ID=$1
REGION="us-central1"
REPO_NAME="arby"
IMAGE_NAME="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/arby-app:latest"
BUCKET_NAME="arby-state-$PROJECT_ID"

echo "--- Building and Pushing Image to Artifact Registry ---"
# Ensure the repository exists
gcloud artifacts repositories create $REPO_NAME \
    --repository-format=docker \
    --location=$REGION \
    --description="Arby Docker Repository" || echo "Repository might already exist."

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
