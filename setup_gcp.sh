#!/bin/bash

# Arby GCP Setup Script
# This script enables necessary APIs and creates the GCS bucket for persistent state.

if [ -z "$1" ]; then
  echo "Usage: ./setup_gcp.sh [PROJECT_ID]"
  exit 1
fi

PROJECT_ID=$1
BUCKET_NAME="arby-state-$PROJECT_ID"
REGION="us-central1" # Default region

echo "--- Configuring gcloud for project: $PROJECT_ID ---"
gcloud config set project $PROJECT_ID

echo "--- Enabling Required APIs ---"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com

echo "--- Creating GCS Bucket: $BUCKET_NAME ---"
# Check if bucket exists
if gsutil ls -b "gs://$BUCKET_NAME" >/dev/null 2>&1; then
  echo "Bucket already exists."
else
  gsutil mb -l $REGION "gs://$BUCKET_NAME"
  echo "Bucket created."
fi

echo "--- Setup Complete ---"
echo "Next step: Build and push the Docker image to Artifact Registry."
