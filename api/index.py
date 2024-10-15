import json
import re
import os
from io import BytesIO
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
from PyPDF2 import PdfReader
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import requests

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

# CORS setup
CORS(app, supports_credentials=True, resources={r"/*": {"origins": "https://portlink-omega.vercel.app/"}})

# OpenAI setup
client = openai.OpenAI(api_key=os.environ['OPENAI'])

# Firebase setup
cred_dict = json.loads(os.environ['FIREBASE_CONFIG'])
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()


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


@app.route('/api/upload', methods=['POST'])
def upload_file():
    logging.debug(f"Received request: {request.method} {request.path}")

    # Log request details
    logging.debug(f"Request headers: {request.headers}")
    logging.debug(f"Request form data: {request.form}")
    logging.debug(f"Request files: {request.files}")

    # Check if file and username are present in the request
    if 'file' not in request.files or 'username' not in request.form:
        logging.error("No file or username in the request.")
        return jsonify({"error": "No file or username in the request"}), 400

    file = request.files['file']
    username = request.form['username']

    # Check if the file is empty
    if file.filename == '':
        logging.error("No file selected.")
        return jsonify({"error": "No selected file"}), 400

    # Validate file format
    if not file.filename.endswith('.pdf'):
        logging.error("Invalid file format. Only PDFs are allowed.")
        return jsonify({"error": "Invalid file format. Please upload a PDF."}), 400

    try:
        # Log file processing steps
        logging.debug(f"Reading file {file.filename} for user {username}")

        file_content = file.read()
        pdf_file = BytesIO(file_content)

        logging.debug(f"Extracting text from PDF file for user {username}")
        resume_text = extract_text_from_pdf(pdf_file)

        logging.debug(
            f"Extracting resume info using OpenAI for user {username}")
        extracted_info = extract_resume_info(resume_text)

        # Log extracted information
        logging.debug(
            f"Extracted resume information for user {username}: {extracted_info}")

        # Save to Firebase Firestore
        doc_ref = db.collection('users').document(username)
        doc_ref.set(extracted_info)

        logging.info(f"Resume data saved successfully for user {username}")
        return jsonify({"success": "File uploaded and data saved successfully", "extracted_info": extracted_info}), 200

    except Exception as e:
        # Log any errors that occur during file processing or data extraction
        logging.error(
            f"Error in upload_file for user {username}: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/resume/<username>', methods=['GET'])
def get_resume_info(username):
    logging.debug(f"Received request: {request.method} {request.path}")
    try:
        resume_ref = db.collection('users').document(username)
        resume_data = resume_ref.get().to_dict()
        if resume_data:
            return jsonify({"extracted_info": resume_data}), 200
        else:
            return jsonify({"error": "Resume data not found"}), 404
    except Exception as e:
        logging.error(f"Error in get_resume_info: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/create-vercel-project', methods=['POST', 'OPTIONS'])
def create_vercel_project():
    logging.debug(f"Received request: {request.method} {request.path}")
    logging.debug(f"Request headers: {request.headers}")
    logging.debug(f"Request body: {request.json}")

    if request.method == 'OPTIONS':
        return handle_preflight()

    data = request.json
    username = data.get('username')
    extracted_info = data.get('extracted_info')

    if not username or not extracted_info:
        return jsonify({"error": "Username and resume info required"}), 400

    subdomain = f"{username}-resume"
    base_domain = os.environ.get('vdomain', 'portlink-omega.vercel.app')
    alias = f"{subdomain}.{base_domain}"

    headers = {
        "Authorization": f"Bearer {os.environ.get('vtoken')}",
        "Content-Type": "application/json"
    }

    url = f"https://api.vercel.com/v2/projects/{os.getenv('vid')}/domains"

    payload = {
        "name": alias
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()

        return jsonify({
            "message": "Resume subdomain created successfully",
            "url": f"https://{alias}"
        }), 200
    except requests.exceptions.RequestException as e:
        logging.error(f"Error creating Vercel subdomain: {str(e)}")
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
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'POST')
    return response


if __name__ == '__main__':
    app.run(debug=True)
