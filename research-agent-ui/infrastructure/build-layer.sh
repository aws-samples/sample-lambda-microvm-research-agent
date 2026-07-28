#!/bin/bash
# Builds a Lambda layer with the latest boto3 that includes lambda-microvms support
set -euo pipefail

LAYER_DIR="lambda-layer"
rm -rf "${LAYER_DIR}"
mkdir -p "${LAYER_DIR}/python"

pip install boto3 botocore -t "${LAYER_DIR}/python" --upgrade --quiet

cd "${LAYER_DIR}"
zip -r ../boto3-layer.zip python -x "*.pyc" "*__pycache__*" > /dev/null

cd ..
rm -rf "${LAYER_DIR}"

echo "Created boto3-layer.zip"
echo ""
echo "Publish the layer:"
echo "  aws lambda publish-layer-version \\"
echo "    --layer-name boto3-latest \\"
echo "    --zip-file fileb://boto3-layer.zip \\"
echo "    --compatible-runtimes python3.12 \\"
echo "    --region us-east-1"
