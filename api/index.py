import uuid
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv
import os
import logging
import base64
import firebase_admin
from firebase_admin import credentials, firestore
from PyPDF2 import PdfReader
from io import BytesIO
import re
import json
import uuid
import click
from requests.exceptions import RequestException
from typing import Dict, Any

# Add these environment variables
VERCEL_API_TOKEN = os.environ.get('vtoken')
VERCEL_TEAM_ID = os.environ.get('VERCEL_TEAM_ID')

app = Flask(__name__)
CORS(app, resources={
     r"/api/*": {"origins": ["https://portlink-omega.vercel.app", "http://localhost:3000"]}})

# OpenAI setup
client = OpenAI(
    api_key=os.environ.get("OPENAI"),
)

GITHUB_REPO = "https://github.com/alok1929/resume-template"


print("openai client creted")

# Firebase setup
cred_dict = json.loads(os.environ['FIREBASE_CONFIG'])
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

print("firebase client created")


@app.route('/', methods=['GET'])
def home():
    return jsonify({"message": "Welcome to the Flask API"}), 200


def extract_text_from_pdf(pdf_file):
    reader = PdfReader(pdf_file)
    text = ""
    for page in reader.pages:
        text += page.extract_text()
    return text


def parse_openai_response(response_text):
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

    extracted_info = {
        "Name": "",
        "Email": "",
        "GitHub": "",
        "LinkedIn": "",
        "Education": [],
        "Professional Experience": [],
        "Projects": [],
        "Questions and Answers": [],
        "Skills": [],
    }

    current_section = None
    for line in response_text.split('\n'):
        line = line.strip()
        if line in extracted_info:
            current_section = line
        elif current_section and line:
            if isinstance(extracted_info[current_section], list):
                extracted_info[current_section].append(line)
            else:
                extracted_info[current_section] = line

    return extracted_info


def extract_resume_info(text):
    prompt = f"""
    Extract the following information from the given resume text:
    1. Name
    2. Email
    3. GitHub (if available)
    4. LinkedIn (if available)
    5. Education (list of degrees)
    6. Professional Experience (list of roles with descriptions and durations)
    7. Projects (list of project names with descriptions and technologies used)
    8. Questions and Answers (list of relevant questions and their answers based on the resume)
    9. Skills (list of skills)

    Resume text:
    {text}

    Format the output as a JSON object with the above fields. Ensure that Professional Experience, Skills, Projects, and Questions and Answers are arrays.
    """

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that extracts information from resumes for an interviewer."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=1000,
        n=1,
        stop=None,
        temperature=0.5,
    )

    try:
        extracted_info = parse_openai_response(
            response.choices[0].message.content.strip())

        for key in ['Name', 'Email', 'GitHub', 'LinkedIn']:
            if key not in extracted_info:
                extracted_info[key] = ""

        for key in ['Education', 'Professional Experience', 'Projects', 'Questions and Answers', 'Skills']:
            if key not in extracted_info or not isinstance(extracted_info[key], list):
                extracted_info[key] = []

        return extracted_info
    except Exception as e:
        raise ValueError(f"Error in parsing OpenAI response: {str(e)}") from e


@app.route('/api/upload', methods=['POST', 'OPTIONS'])
def upload_file():
    if request.method == 'OPTIONS':
        # Preflight request. Reply successfully:
        response = app.make_default_options_response()
    else:
        # Actual request
        try:
            if 'file' not in request.files:
                return jsonify({'error': 'No file part in the request'}), 400

            file = request.files['file']
            username = request.form.get('username')
            filename = request.form.get('filename')

            if file.filename == '' or not username or not filename:
                return jsonify({'error': 'Missing file, username, or filename'}), 400

            # Verify file is a PDF
            if not file.filename.lower().endswith('.pdf'):
                return jsonify({'error': 'Only PDF files are allowed'}), 400

            # Process file here
            file_content = file.read()

            # Extract text from PDF
            pdf_text = extract_text_from_pdf(BytesIO(file_content))

            # Extract resume information
            resume_info = extract_resume_info(pdf_text)

            # Save to Firestore
            doc_ref = db.collection('users').document(username)
            doc_ref.set({
                'resumeInfo': resume_info,
                'filename': filename,
                'originalFilename': file.filename
            })

            response = jsonify({
                'message': 'File uploaded, processed, and saved to database successfully!',
                'username': username,
                'filename': filename,
                'original_filename': file.filename,
                'size': len(file_content),
                'type': file.content_type,
                'resume_info': resume_info  # Make sure this is included
            })
        except Exception as e:
            print(f"Error processing file: {str(e)}")
            response = jsonify(
                {'error': f'Internal server error: {str(e)}'}), 500

    # Add CORS headers to the response
    response.headers.add('Access-Control-Allow-Origin',
                         'https://portlink-omega.vercel.app')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')

    return response


@app.route('/api/resume/<username>', methods=['GET'])
def get_resume_info(username):
    logging.debug(f"Received request: {request.method} {request.path}")

    try:
        # Retrieve the document reference from the Firestore 'users' collection
        resume_ref = db.collection('users').document(username)
        resume_data = resume_ref.get().to_dict()

        # If resume data exists, return it with a 200 status code
        if resume_data:
            return jsonify({"extracted_info": resume_data}), 200
        else:
            return jsonify({"error": "Resume data not found"}), 404

    except Exception as e:
        # Log the error and return a 500 status code with error message
        logging.error(f"Error in get_resume_info: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/create-vercel-project', methods=['POST'])
def create_vercel_project():
    try:
        # Get JSON payload
        data = request.get_json(force=True)
        if not data or 'username' not in data:
            return jsonify({"error": "Missing data", "details": "Username is required in the request body"}), 400

        username = data['username']
        base_project_name = f"{username}-resume"
        project_name = base_project_name

        headers = {
            "Authorization": f"Bearer {VERCEL_API_TOKEN}",
            "Content-Type": "application/json"
        }

        # Try to create the project, handle conflict if it exists
        max_retries = 3
        for attempt in range(max_retries):
            create_project_data = {
                "name": project_name,
                "framework": "nextjs"
            }

            create_response = requests.post(
                "https://api.vercel.com/v9/projects",
                headers=headers,
                json=create_project_data
            )

            if create_response.status_code == 409:
                # Project name conflict, append a unique identifier
                project_name = f"{base_project_name}-{uuid.uuid4().hex[:6]}"
                if attempt == max_retries - 1:
                    return jsonify({"error": "Failed to create project after multiple attempts", "details": "Name conflict persists"}), 409
            elif create_response.status_code in (200, 201):
                # Project created successfully
                break
            else:
                # Other error occurred
                create_response.raise_for_status()

        project_info = create_response.json()
        project_id = project_info['id']

        # Step 2: Create initial deployment with files
        # (Keep your existing files dictionary here)

        deployment_data = {
            "name": project_name,
            "files": [
                {
                    "file": file,
                    "data": json.dumps(content) if isinstance(content, dict) else content
                } for file, content in files.items()
            ],
            "projectSettings": {
                "framework": "nextjs"
            }
        }

        deployment_response = requests.post(
            "https://api.vercel.com/v13/deployments",
            headers=headers,
            json=deployment_data
        )

        deployment_response.raise_for_status()

        # Send success response
        return jsonify({
            "success": True,
            "message": "Vercel project created and deployed successfully!",
            "projectId": project_id,
            "projectName": project_name,
            "deploymentUrl": deployment_response.json().get('url')
        }), 201

    except RequestException as e:
        # Handle network-related errors
        return jsonify({"error": "Failed to communicate with Vercel API", "details": str(e)}), 500
    except Exception as e:
        # Handle any other unexpected errors
        return jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500
