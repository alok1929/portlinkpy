@app.route('/api/create-vercel-project', methods=['POST'])
def create_vercel_project():
    try:
        # Get JSON payload
        data = request.get_json(force=True)
        if not data:
            return jsonify({
                "error": "Missing data",
                "details": "The request body cannot be empty"
            }), 400

        username = data.get('username')
        if not username:
            return jsonify({
                "error": "Missing username",
                "details": "Username is required in the request body"
            }), 400

        VERCEL_API_TOKEN = os.environ.get('VERCEL_API_TOKEN')
        if not VERCEL_API_TOKEN:
            logging.error("Vercel API token not configured")
            return jsonify({
                "error": "Server configuration error",
                "details": "Vercel API token is missing"
            }), 500

        GITHUB_REPO = os.environ.get('GITHUB_REPO')
        if not GITHUB_REPO:
            logging.error("GitHub repo not configured")
            return jsonify({
                "error": "Server configuration error",
                "details": "GitHub repo is missing"
            }), 500

        project_name = f"{username}-resume"

        # Prepare project configuration for Vercel
        project_data = {
            "name": project_name,
            "framework": "nextjs",
            "gitRepository": {
                "type": "github",
                "repo": GITHUB_REPO,
            },
            "buildCommand": "npm run build",
            "installCommand": "npm install",
            "environmentVariables": [
                {
                    "key": "NEXT_PUBLIC_RESUME_USERNAME",
                    "value": username,
                    "target": ["production", "preview", "development"]
                }
            ]
        }

        VERCEL_TEAM_ID = os.environ.get('VERCEL_TEAM_ID')
        if VERCEL_TEAM_ID:
            project_data["teamId"] = VERCEL_TEAM_ID

        # Headers for Vercel API
        headers = {
            "Authorization": f"Bearer {VERCEL_API_TOKEN}",
            "Content-Type": "application/json"
        }

        # Send request to create the project
        create_response = requests.post(
            "https://api.vercel.com/v9/projects",
            headers=headers,
            json=project_data
        )
        create_response.raise_for_status()

        project_info = create_response.json()

        # Trigger deployment
        deployment_data = {
            "name": project_name,
            "target": "production",
            "gitSource": {
                "type": "github",
                "repo": GITHUB_REPO,
                "ref": "main"
            }
        }

        if VERCEL_TEAM_ID:
            deployment_data["teamId"] = VERCEL_TEAM_ID

        # Send request to deploy the project
        deploy_response = requests.post(
            "https://api.vercel.com/v13/deployments",
            headers=headers,
            json=deployment_data
        )
        deploy_response.raise_for_status()

        project_url = f"https://{project_name}.vercel.app"

        return jsonify({
            "message": "Vercel project created and deployed successfully",
            "url": project_url,
            "project_id": project_info.get("id")
        }), 200

    except requests.exceptions.RequestException as e:
        logging.error(f"Vercel API error: {str(e)}")
        return jsonify({
            "error": "Vercel API error",
            "details": str(e)
        }), 500

    except Exception as e:
        logging.exception(f"Unexpected error: {str(e)}")
        return jsonify({
            "error": "An unexpected error occurred",
            "details": str(e)
        }), 500
