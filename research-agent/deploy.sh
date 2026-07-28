#!/bin/bash
# Deploy script for Research Agent on Lambda MicroVMs
set -euo pipefail

STACK_NAME="${CFN_STACK_NAME:-research-agent-infra}"
IMAGE_NAME="${MICROVM_IMAGE_NAME:-research-agent}"
REGION="${AWS_REGION:-us-east-1}"

# Load values from CloudFormation stack outputs
_get_stack_output() {
    aws cloudformation describe-stacks \
        --stack-name "${STACK_NAME}" \
        --region "${REGION}" \
        --query "Stacks[0].Outputs[?OutputKey=='${1}'].OutputValue" \
        --output text 2>/dev/null || echo ""
}

S3_BUCKET="${DEPLOY_S3_BUCKET:-$(_get_stack_output ArtifactsBucketName)}"
BUILD_ROLE_ARN="${BUILD_ROLE_ARN:-$(_get_stack_output BuildRoleArn)}"
EXECUTION_ROLE_ARN="${EXECUTION_ROLE_ARN:-$(_get_stack_output ExecutionRoleArn)}"
AGENTCORE_GATEWAY_URL="${AGENTCORE_GATEWAY_URL:-$(_get_stack_output AgentCoreGatewayUrl)}"

usage() {
    echo "Usage: $0 {infra|add-target|package|create-image|run <task>|status <id>|shell <id>}"
    echo ""
    echo "Commands:"
    echo "  infra          - Deploy/update CloudFormation infrastructure stack"
    echo "  add-target     - Add web search connector to the gateway (run once after infra)"
    echo "  package        - Package agent code into deployment zip"
    echo "  create-image   - Upload to S3 and create/update MicroVM image"
    echo "  run <task>     - Launch a MicroVM to run the agent"
    echo "  status <id>    - Check MicroVM status"
    echo "  shell <id>     - Connect to a running MicroVM shell"
    echo ""
    echo "Environment:"
    echo "  CFN_STACK_NAME     - CloudFormation stack name (default: research-agent-infra)"
    echo "  AWS_REGION         - AWS region (default: us-east-1)"
    echo "  MICROVM_IMAGE_NAME - MicroVM image name (default: research-agent)"
    exit 1
}

deploy_infra() {
    local template_file="infrastructure/template.yaml"
    if [ ! -f "${template_file}" ]; then
        echo "ERROR: ${template_file} not found. Run from the research-agent directory."
        exit 1
    fi

    echo "Deploying CloudFormation stack: ${STACK_NAME}..."
    if ! aws cloudformation deploy \
        --stack-name "${STACK_NAME}" \
        --template-file "${template_file}" \
        --capabilities CAPABILITY_NAMED_IAM \
        --region "${REGION}" \
        --no-fail-on-empty-changeset; then

        echo ""
        echo "Deployment failed. Fetching stack events..."
        aws cloudformation describe-stack-events \
            --stack-name "${STACK_NAME}" \
            --region "${REGION}" \
            --query "StackEvents[?ResourceStatus=='CREATE_FAILED' || ResourceStatus=='UPDATE_FAILED'].[LogicalResourceId,ResourceStatusReason]" \
            --output table
        exit 1
    fi

    echo ""
    echo "Stack outputs:"
    aws cloudformation describe-stacks \
        --stack-name "${STACK_NAME}" \
        --region "${REGION}" \
        --query "Stacks[0].Outputs[*].[OutputKey,OutputValue]" \
        --output table
}

add_target() {
    local gateway_id
    gateway_id=$(_get_stack_output AgentCoreGatewayId)

    if [ -z "${gateway_id}" ]; then
        echo "ERROR: Gateway not found. Run './deploy.sh infra' first."
        exit 1
    fi

    local existing
    existing=$(aws bedrock-agentcore-control list-gateway-targets \
        --gateway-identifier "${gateway_id}" \
        --region "${REGION}" \
        --query "targets[?name=='web-search-tool'].targetId" \
        --output text 2>/dev/null || echo "")

    if [ -n "${existing}" ] && [ "${existing}" != "None" ]; then
        echo "Web search target already exists (${existing}). Skipping."
        return 0
    fi

    echo "Adding web search connector target to gateway ${gateway_id}..."
    aws bedrock-agentcore-control create-gateway-target \
        --gateway-identifier "${gateway_id}" \
        --name "web-search-tool" \
        --target-configuration '{
            "mcp": {
                "connector": {
                    "source": {"connectorId": "web-search"},
                    "configurations": [{"name": "WebSearch", "parameterValues": {}}]
                }
            }
        }' \
        --credential-provider-configurations '[{"credentialProviderType": "GATEWAY_IAM_ROLE"}]' \
        --region "${REGION}"

    echo "Web search target added successfully."
}

package() {
    echo "Packaging agent code..."
    rm -f agent-package.zip
    zip -r agent-package.zip Dockerfile requirements.txt agent/ -x "agent/__pycache__/*"
    echo "Created agent-package.zip"
}

create_image() {
    echo "Uploading package to S3..."
    aws s3 cp agent-package.zip "s3://${S3_BUCKET}/${IMAGE_NAME}/agent-package.zip"

    local account_id
    account_id=$(aws sts get-caller-identity --query 'Account' --output text)
    local image_arn="arn:aws:lambda:${REGION}:${account_id}:microvm-image:${IMAGE_NAME}"
    local hooks_config='{"port":9000,"microvmImageHooks":{"ready":"ENABLED"},"microvmHooks":{"run":"ENABLED"}}'

    if aws lambda-microvms get-microvm-image --image-identifier "${image_arn}" --region "${REGION}" >/dev/null 2>&1; then
        echo "Image exists. Updating..."
        aws lambda-microvms update-microvm-image \
            --image-identifier "${image_arn}" \
            --code-artifact "uri=s3://${S3_BUCKET}/${IMAGE_NAME}/agent-package.zip" \
            --base-image-arn "arn:aws:lambda:${REGION}:aws:microvm-image:al2023-1" \
            --build-role-arn "${BUILD_ROLE_ARN}" \
            --hooks "${hooks_config}" \
            --logging '{"cloudWatch":{"logGroup":"/aws/lambda-microvms/research-agent"}}' \
            --region "${REGION}"
    else
        echo "Creating MicroVM image..."
        aws lambda-microvms create-microvm-image \
            --name "${IMAGE_NAME}" \
            --code-artifact "uri=s3://${S3_BUCKET}/${IMAGE_NAME}/agent-package.zip" \
            --base-image-arn "arn:aws:lambda:${REGION}:aws:microvm-image:al2023-1" \
            --build-role-arn "${BUILD_ROLE_ARN}" \
            --hooks "${hooks_config}" \
            --logging '{"cloudWatch":{"logGroup":"/aws/lambda-microvms/research-agent"}}' \
            --region "${REGION}"
    fi

    echo ""
    echo "Waiting for image build..."
    local state="CREATING"
    local attempts=0
    while [ "${state}" = "CREATING" ] || [ "${state}" = "UPDATING" ]; do
        sleep 10
        attempts=$((attempts + 1))
        state=$(aws lambda-microvms get-microvm-image \
            --image-identifier "${image_arn}" \
            --region "${REGION}" \
            --query 'state' --output text 2>/dev/null || echo "UNKNOWN")
        echo "  [${attempts}] State: ${state}"
        if [ ${attempts} -ge 60 ]; then
            echo "Timeout waiting for image build."
            break
        fi
    done

    if [ "${state}" = "CREATED" ] || [ "${state}" = "UPDATED" ]; then
        echo "Image build SUCCEEDED!"
    else
        echo ""
        echo "Image build FAILED (state: ${state})"
        _fetch_build_logs
        exit 1
    fi
}

_fetch_build_logs() {
    local log_group="/aws/lambda/microvms/${IMAGE_NAME}"
    echo "Fetching logs from: ${log_group}"

    local streams
    streams=$(aws logs describe-log-streams \
        --log-group-name "${log_group}" \
        --order-by LastEventTime --descending --limit 3 \
        --region "${REGION}" \
        --query 'logStreams[*].logStreamName' --output text 2>/dev/null || echo "")

    if [ -n "${streams}" ] && [ "${streams}" != "None" ]; then
        for stream in ${streams}; do
            echo ""
            echo "=== ${stream} ==="
            aws logs get-log-events \
                --log-group-name "${log_group}" \
                --log-stream-name "${stream}" \
                --region "${REGION}" \
                --limit 50 \
                --query 'events[*].message' --output text 2>/dev/null
        done
    else
        echo "No logs found."
    fi
}

run_agent() {
    local task="${1:?Task is required}"
    echo "Research task: ${task}"

    local safe_task
    safe_task=$(printf '%s' "${task}" | tr -d "'\"\`\$\\")

    local account_id
    account_id=$(aws sts get-caller-identity --query 'Account' --output text)
    local image_arn="arn:aws:lambda:${REGION}:${account_id}:microvm-image:${IMAGE_NAME}"

    # Check for a running MicroVM from this image
    local microvm_id=""
    local endpoint=""
    local running_vm
    running_vm=$(aws lambda-microvms list-microvms \
        --region "${REGION}" \
        --query "items[?imageArn=='${image_arn}' && state=='RUNNING'].microvmId | [0]" \
        --output text 2>/dev/null || echo "")

    if [ -n "${running_vm}" ] && [ "${running_vm}" != "None" ]; then
        microvm_id="${running_vm}"
        # Get endpoint from get-microvm
        endpoint=$(aws lambda-microvms get-microvm \
            --microvm-identifier "${microvm_id}" \
            --region "${REGION}" \
            --query 'endpoint' --output text)
        echo "Reusing running MicroVM: ${microvm_id}"
    else
        # Launch a new MicroVM
        echo "No running MicroVM found. Launching..."
        local resp
        resp=$(aws lambda-microvms run-microvm \
            --image-identifier "${image_arn}" \
            --execution-role-arn "${EXECUTION_ROLE_ARN}" \
            --ingress-network-connectors "arn:aws:lambda:${REGION}:aws:network-connector:aws-network-connector:HTTP_INGRESS" \
            --egress-network-connectors "arn:aws:lambda:${REGION}:aws:network-connector:aws-network-connector:INTERNET_EGRESS" \
            --idle-policy '{"maxIdleDurationSeconds":300,"suspendedDurationSeconds":60,"autoResumeEnabled":true}' \
            --logging '{"cloudWatch":{"logGroup":"/aws/lambda-microvms/research-agent"}}' \
            --region "${REGION}")

        microvm_id=$(echo "${resp}" | jq -r '.microvmId')
        endpoint=$(echo "${resp}" | jq -r '.endpoint')

        echo "MicroVM ID: ${microvm_id}"
        echo "Endpoint:   ${endpoint}"

        # Wait for RUNNING state
        echo "Waiting for MicroVM to start..."
        local state="PENDING"
        while [ "${state}" = "PENDING" ]; do
            sleep 2
            state=$(aws lambda-microvms get-microvm \
                --microvm-identifier "${microvm_id}" \
                --region "${REGION}" \
                --query 'state' --output text)
        done

        if [ "${state}" != "RUNNING" ]; then
            echo "ERROR: MicroVM failed to start (state: ${state})"
            exit 1
        fi
        echo "MicroVM is RUNNING."
    fi

    # Generate auth token
    local auth_token
    auth_token=$(aws lambda-microvms create-microvm-auth-token \
        --microvm-identifier "${microvm_id}" \
        --region "${REGION}" \
        --expiration-in-minutes 30 \
        --allowed-ports 'allPorts={}' \
        --query 'authToken."X-aws-proxy-auth"' --output text)

    # Ensure gateway URL is resolved
    if [ -z "${AGENTCORE_GATEWAY_URL}" ]; then
        AGENTCORE_GATEWAY_URL=$(aws cloudformation describe-stacks \
            --stack-name "${STACK_NAME}" --region "${REGION}" \
            --query "Stacks[0].Outputs[?OutputKey=='AgentCoreGatewayUrl'].OutputValue" \
            --output text 2>/dev/null || echo "")
    fi
    if [ -z "${AGENTCORE_GATEWAY_URL}" ]; then
        echo "WARNING: AgentCore Gateway URL not found. Web search will not work."
    fi

    # Send research request
    echo "Sending research request..."
    echo ""
    curl -s --max-time 120 -X POST "https://${endpoint}/research" \
        -H "X-aws-proxy-auth: ${auth_token}" \
        -H "Content-Type: application/json" \
        -d "{\"task\":\"${safe_task}\",\"gatewayUrl\":\"${AGENTCORE_GATEWAY_URL}\"}" | python3 -m json.tool 2>/dev/null || echo "Request timed out or returned empty. Check CloudWatch logs."

    echo ""
    echo "MicroVM: ${microvm_id} (auto-resumes on traffic, suspends after 5 min idle)"
}

status() {
    local id="${1:?MicroVM ID is required}"
    aws lambda-microvms get-microvm \
        --microvm-identifier "${id}" \
        --region "${REGION}"
}

shell_connect() {
    local id="${1:?MicroVM ID is required}"
    local token
    token=$(aws lambda-microvms create-microvm-shell-auth-token \
        --microvm-identifier "${id}" \
        --expiration-in-minutes 30 \
        --region "${REGION}" | jq -r '.authToken."X-aws-proxy-auth"')

    local endpoint
    endpoint=$(aws lambda-microvms get-microvm \
        --microvm-identifier "${id}" \
        --query endpoint --output text \
        --region "${REGION}")

    echo "Connecting to MicroVM shell..."
    (stty raw -echo; websocat --binary --header="X-aws-proxy-auth: ${token}" "wss://${endpoint}"; stty sane)
}

case "${1:-}" in
    infra)          deploy_infra ;;
    add-target)     add_target ;;
    package)        package ;;
    create-image)   create_image ;;
    run)            run_agent "${2:-}" ;;
    status)         status "${2:-}" ;;
    shell)          shell_connect "${2:-}" ;;
    *)              usage ;;
esac
