import json
import re
import os
from io import BytesIO
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
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

CORS(app, resources={
    r"/*": {  # This will allow CORS for all routes
        "origins": [
            "https://portlink-omega.vercel.app",
            "http://localhost:3000",
            "https://*.vercel.app"  # This will allow all Vercel preview deployments
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Accept", "Origin"],
        "supports_credentials": True,
        "max_age": 3600
    }
})
# OpenAI setup
client = OpenAI(
    # This is the default and can be omitted
    api_key=os.environ.get("OPENAI"),
)
print("openai api")

# Firebase setup
cred_dict = json.loads(os.environ['FIREBASE_CONFIG'])
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()


@app.route('/')
def home():
    return "Flask app is running!", 200


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
    try:
        # Check for file in request
        if 'file' not in request.files:
            return jsonify({'error': 'No file part in the request'}), 400

        file = request.files['file']

        # Check if file was selected
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        # Verify file is a PDF
        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'error': 'Only PDF files are allowed'}), 400

        # Read file content
        file_content = file.read()
        pdf_file = BytesIO(file_content)

        # Extract text and process resume
        try:
            resume_text = extract_text_from_pdf(pdf_file)
            extracted_info = extract_resume_info(resume_text)

            # Save to Firestore if username is provided
            username = request.form.get('username')
            if username:
                doc_ref = db.collection('users').document(username)
                doc_ref.set(extracted_info)

            return jsonify({
                'success': True,
                'message': 'File processed successfully!',
                'filename': file.filename,
                'extracted_info': extracted_info
            })

        except Exception as process_error:
            return jsonify({
                'error': f'Error processing resume: {str(process_error)}'
            }), 422  # Unprocessable Entity

    except Exception as e:
        print(f"Error processing file: {str(e)}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500


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
    logging.debug(f"Received request: {request.method} {request.path}")
    logging.debug(f"Request headers: {request.headers}")
    logging.debug(f"Request body: {request.json}")

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


@app.after_request
def after_request(response):
    # Get the origin from the request headers
    origin = request.headers.get('Origin')
    allowed_origins = [
        "https://portlink-omega.vercel.app",
        "http://localhost:3000",
        "https://*.vercel.app"
    ]

    # Check if the origin is allowed
    if origin:
        for allowed_origin in allowed_origins:
            if allowed_origin.endswith('*.vercel.app'):
                if origin.endswith('.vercel.app'):
                    response.headers['Access-Control-Allow-Origin'] = origin
                    break
            elif origin == allowed_origin:
                response.headers['Access-Control-Allow-Origin'] = origin
                break

    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Accept, Origin'
    return response


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500


app.route('/', methods=['OPTIONS'])


def handle_preflight():
    response = jsonify({'message': 'Preflight request successful'})
    return response


if __name__ == "__main__":
    app.run(debug=True)
