import json
import re

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import openai
from PyPDF2 import PdfReader
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "http://localhost:3000"}})

# Enable CORS for all routes
CORS(app)

# OpenAI setup
client = openai.OpenAI(api_key=os.environ['OPENAI'])

# Firebase setup
cred = credentials.Certificate(os.environ['FIREBASE_CONFIG'])
firebase_admin.initialize_app(cred)
db = firestore.client()


def extract_text_from_pdf(pdf_path):
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text()
    return text


def parse_openai_response(response_text):
    # Try to parse the entire response as JSON
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # If that fails, try to extract JSON from the text
    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # If JSON extraction fails, parse the text manually
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

    Format the output as a JSON object with the above fields. Ensure that Professional Experience,Skills, Projects, and Questions and Answers are arrays.
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

        # Ensure all required fields are present and in the correct format
        for key in ['Name', 'Email', 'GitHub', 'LinkedIn']:
            if key not in extracted_info:
                extracted_info[key] = ""

        for key in ['Education', 'Professional Experience', 'Projects', 'Questions and Answers', 'Skills']:
            if key not in extracted_info or not isinstance(extracted_info[key], list):
                extracted_info[key] = []

        return extracted_info
    except Exception as e:
        raise ValueError(f"Error in parsing OpenAI response: {str(e)}") from e


UPLOAD_FOLDER = './uploads'
DATA_FOLDER = './data'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['DATA_FOLDER'] = DATA_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DATA_FOLDER, exist_ok=True)


@app.route('/resume/<username>', methods=['GET'])
def get_resume_info(username):
    try:
        resume_ref = db.collection('users').document(username)
        resume_data = resume_ref.get().to_dict()
        if resume_data:
            return jsonify({"extracted_info": resume_data}), 200
        else:
            return jsonify({"error": "Resume data not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files or 'username' not in request.form:
        return jsonify({"error": "No file part or username in the request"}), 400

    file = request.files['file']
    username = request.form['username']

    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if not file.filename.endswith('.pdf'):
        return jsonify({"error": "Invalid file format. Please upload a PDF."}), 400

    file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(file_path)

    try:
        resume_text = extract_text_from_pdf(file_path)
        extracted_info = extract_resume_info(resume_text)

        doc_ref = db.collection('users').document(username)
        doc_ref.set(extracted_info)

        return jsonify({"success": "File uploaded and data saved successfully", "extracted_info": extracted_info}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


VERCEL_PROJECT_ID = "team_zx1T3VUMMDpm6GpVRHXgV9Hi"


@app.route('/create-vercel-project', methods=['POST', 'OPTIONS'])
def create_vercel_project():
    if request.method == 'OPTIONS':
        return handle_preflight()

    data = request.json
    username = data.get('username')
    extracted_info = data.get('extracted_info')

    if not username or not extracted_info:
        return jsonify({"error": "Username and resume info required"}), 400

    # Create a new alias (subdomain) for the existing project
    subdomain = f"{username}-resume"
    alias = f"{subdomain}.{os.environ('VERCEL_DOMAIN', 'paperu-rho.vercel.app')}"

    headers = {
        "Authorization": f"Bearer {os.environ('VERCEL_TOKEN')}",
        "Content-Type": "application/json"
    }

    # API endpoint to add a new alias
    url = f"https://api.vercel.com/v2/projects/{os.getenv('VERCEL_PROJECT_ID')}/domains"

    payload = {
        "name": alias
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()  # This will raise an exception for HTTP errors

        return jsonify({
            "message": "Resume subdomain created successfully",
            "url": f"https://{alias}"
        }), 200
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error creating Vercel subdomain: {str(e)}")
        return jsonify({
            "error": "Failed to create subdomain",
            "details": str(e)
        }), 500


@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500


def handle_preflight():
    response = jsonify({'message': 'Preflight request successful'})
    response.headers.add('Access-Control-Allow-Origin',
                         'http://localhost:3000')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'POST')
    return response


if __name__ == '__main__':
    app.run(debug=True)
