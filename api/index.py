import uuid
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv
import os
import logging
import firebase_admin
from firebase_admin import credentials, firestore
from PyPDF2 import PdfReader
from io import BytesIO
import re
import uuid
import json
import requests
from requests.exceptions import RequestException

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
                "framework": "nextjs",
                 "environmentVariables": [
                    {
                        "key": "NEXT_PUBLIC_RESUME_USERNAME",
                        "value": username,
                        "target": ["production", "preview", "development"]
                    }
                ]
            }

            create_response = requests.post(
                "https://api.vercel.com/v9/projects",
                headers=headers,
                json=create_project_data
            )

            if create_response.status_code == 409:
                project_name = f"{base_project_name}-{uuid.uuid4().hex[:6]}"
                if attempt == max_retries - 1:
                    return jsonify({"error": "Failed to create project after multiple attempts", "details": "Name conflict persists"}), 409
            elif create_response.status_code in (200, 201):
                break
            else:
                error_message = f"Vercel API error: {create_response.status_code} - {create_response.text}"
                # Log the error
                print(f"Project creation failed: {error_message}")
                return jsonify({"error": "Failed to create project", "details": error_message}), create_response.status_code

        project_info = create_response.json()
        project_id = project_info['id']
        print(f"Project created successfully. ID: {project_id}")

        # Define the files for the initial deployment
        files = {
            'package.json': json.dumps({
                "name": project_name,
                "version": "0.1.0",
                "private": True,
                "scripts": {
                    "dev": "next dev",
                    "build": "next build",
                    "start": "next start",
                    "lint": "next lint"
                },
                "dependencies": {
                    "@radix-ui/react-icons": "^1.3.0",
                    "@radix-ui/react-separator": "^1.1.0",
                    "@radix-ui/react-slot": "^1.1.0",
                    "class-variance-authority": "^0.7.0",
                    "clsx": "^2.1.1",
                    "lucide-react": "^0.453.0",
                    "next": "14.2.15",
                    "react": "^18",
                    "react-dom": "^18",
                    "tailwind-merge": "^2.5.4",
                    "tailwindcss-animate": "^1.0.7"
                },
                "devDependencies": {
                    "@types/node": "^20",
                    "@types/react": "^18",
                    "@types/react-dom": "^18",
                    "eslint": "^8",
                    "eslint-config-next": "14.2.15",
                    "postcss": "^8",
                    "tailwindcss": "^3.4.1",
                    "typescript": "^5"
                }
            }, indent=2),
            'tsconfig.json': json.dumps({
                "compilerOptions": {
                    "target": "es5",
                    "lib": ["dom", "dom.iterable", "esnext"],
                    "allowJs": True,
                    "skipLibCheck": True,
                    "strict": True,
                    "noEmit": True,
                    "esModuleInterop": True,
                    "module": "esnext",
                    "moduleResolution": "bundler",
                    "resolveJsonModule": True,
                    "isolatedModules": True,
                    "jsx": "preserve",
                    "incremental": True,
                    "plugins": [
                        {
                            "name": "next"
                        }
                    ],
                    "paths": {
                        "@/*": ["./src/*"]
                    }
                },
                "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
                "exclude": ["node_modules"]
            }, indent=2),
            'src/app/page.tsx': """
'use client'

import { useEffect, useState } from 'react'
import { Mail, Linkedin, Book, Briefcase, Code, Star } from 'lucide-react'

interface ResumeInfo {
  Name: string
  Email: string
  GitHub: string
  LinkedIn: string
  Education: string[]
  "Professional Experience": Array<{
    Role: string
    Duration: string
    Description: string
  }>
  Projects: Array<{
    Name: string
    Description: string
    Technologies: string[]
  }>
  Skills: string[]
  "Questions and Answers": Array<{
    Question: string
    Answer: string
  }>
}

export default function PortfolioResume() {
  const [resumeInfo, setResumeInfo] = useState<ResumeInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchResumeData = async () => {
      try {
        const username = process.env.NEXT_PUBLIC_RESUME_USERNAME
        if (!username) {
          throw new Error('Username not configured')
        }

        const response = await fetch(`https://portlinkpy.vercel.app/api/resume/${username}`)
        if (!response.ok) {
          throw new Error('Failed to fetch resume data')
        }

        const data = await response.json()
        setResumeInfo(data.extracted_info.resumeInfo)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load resume')
      } finally {
        setLoading(false)
      }
    }

    fetchResumeData()
  }, [])

  if (loading) {
    return <div className="flex justify-center items-center min-h-screen">Loading...</div>
  }

  if (error) {
    return <div className="flex justify-center items-center min-h-screen text-red-500">{error}</div>
  }

  if (!resumeInfo) {
    return <div className="flex justify-center items-center min-h-screen">No resume data found</div>
  }

  return (
    <div className="bg-gray-50 min-h-screen">
      <div className="container mx-auto px-4 py-8">
        <div className="lg:flex lg:space-x-8">
          {/* Sidebar */}
          <aside className="lg:w-1/3 mb-8 lg:mb-0">
            <div className="bg-white shadow rounded-lg p-6">
              <h2 className="text-3xl font-bold text-center mb-4">{resumeInfo.Name}</h2>
              <div className="space-y-4">
                <a
                  href={`mailto:${resumeInfo.Email}`}
                  className="flex items-center justify-center text-blue-600 border border-blue-600 p-2 rounded-lg hover:bg-blue-50 transition"
                >
                  <Mail className="w-4 h-4 mr-2" />
                  {resumeInfo.Email}
                </a>
                {resumeInfo.GitHub && (
                  <a
                    href={resumeInfo.GitHub}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center justify-center text-blue-600 border border-blue-600 p-2 rounded-lg hover:bg-blue-50 transition"
                  >
                    GitHub
                  </a>
                )}
                {resumeInfo.LinkedIn && (
                  <a
                    href={resumeInfo.LinkedIn}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center justify-center text-blue-600 border border-blue-600 p-2 rounded-lg hover:bg-blue-50 transition"
                  >
                    <Linkedin className="w-4 h-4 mr-2" />
                    LinkedIn
                  </a>
                )}
              </div>
              <hr className="my-6" />
              <div>
                <h3 className="text-xl font-semibold flex items-center">
                  <Star className="w-5 h-5 mr-2" />
                  Skills
                </h3>
                <div className="flex flex-wrap gap-2 mt-2">
                  {resumeInfo.Skills.map((skill, index) => (
                    <span key={index} className="px-2 py-1 bg-gray-200 rounded text-sm">
                      {skill}
                    </span>
                  ))}
                </div>
              </div>
              <hr className="my-6" />
              <div>
                <h3 className="text-xl font-semibold flex items-center">
                  <Book className="w-5 h-5 mr-2" />
                  Education
                </h3>
                <ul className="list-disc ml-6 mt-2 space-y-2">
                  {resumeInfo.Education.map((edu, index) => (
                    <li key={index} className="text-gray-600">{edu}</li>
                  ))}
                </ul>
              </div>
            </div>
          </aside>

          {/* Main Content */}
          <main className="lg:w-2/3 space-y-8">
            {/* Professional Experience Section */}
            <div className="bg-white shadow rounded-lg p-6">
              <h2 className="text-2xl font-bold flex items-center mb-6">
                <Briefcase className="w-6 h-6 mr-2" />
                Professional Experience
              </h2>
              {resumeInfo["Professional Experience"].map((exp, index) => (
                <div key={index} className="mb-6">
                  <h3 className="text-xl font-semibold">{exp.Role}</h3>
                  <p className="text-gray-500 mb-2">{exp.Duration}</p>
                  <p>{exp.Description}</p>
                </div>
              ))}
            </div>

            {/* Projects Section */}
            <div className="bg-white shadow rounded-lg p-6">
              <h2 className="text-2xl font-bold flex items-center mb-6">
                <Code className="w-6 h-6 mr-2" />
                Projects
              </h2>
              {resumeInfo.Projects.map((project, index) => (
                <div key={index} className="mb-6">
                  <h3 className="text-xl font-semibold">{project.Name}</h3>
                  <p className="mb-2">{project.Description}</p>
                  <div className="flex flex-wrap gap-2">
                    {project.Technologies.map((tech, techIndex) => (
                      <span key={techIndex} className="px-2 py-1 border border-gray-300 rounded text-sm">
                        {tech}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {/* Q&A Section */}
            <div className="bg-white shadow rounded-lg p-6">
              <h2 className="text-2xl font-bold">Questions & Answers</h2>
              {resumeInfo["Questions and Answers"].map((qa, index) => (
                <div key={index} className="mb-6">
                  <h3 className="text-xl font-semibold mb-2">Q: {qa.Question}</h3>
                  <p>A: {qa.Answer}</p>
                </div>
              ))}
            </div>
          </main>
        </div>
      </div>
    </div>
  )
}
            """,
            'src/app/layout.tsx': """
import './globals.css'
import type { Metadata } from 'next'
import { Inter } from 'next/font/google'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Create Next App',
  description: 'Generated by create next app',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={inter.className}>{children}</body>
    </html>
  )
}
            """,
            'src/app/globals.css': """
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --foreground-rgb: 0, 0, 0;
  --background-start-rgb: 214, 219, 220;
  --background-end-rgb: 255, 255, 255;
}

@media (prefers-color-scheme: dark) {
  :root {
    --foreground-rgb: 255, 255, 255;
    --background-start-rgb: 0, 0, 0;
    --background-end-rgb: 0, 0, 0;
  }
}

body {
  color: rgb(var(--foreground-rgb));
  background: linear-gradient(
      to bottom,
      transparent,
      rgb(var(--background-end-rgb))
    )
    rgb(var(--background-start-rgb));
}
            """
        }

        # Create initial deployment with files
        deployment_data = {
            "name": project_name,
            "files": [
                {
                    "file": file,
                    "data": content
                } for file, content in files.items()
            ],
            "projectId": project_id,
            "target": "production",
            "framework": "nextjs"
        }

        deployment_response = requests.post(
            "https://api.vercel.com/v13/deployments",
            headers=headers,
            json=deployment_data
        )

        if deployment_response.status_code not in (200, 201):
            error_message = f"Vercel deployment error: {deployment_response.status_code} - {deployment_response.text}"
            return jsonify({"error": "Failed to deploy project", "details": error_message}), deployment_response.status_code

        deployment_info = deployment_response.json()

        return jsonify({
            "success": True,
            "message": "Vercel project created and deployed successfully!",
            "projectId": project_id,
            "projectName": project_name,
            "deploymentUrl": deployment_info.get('url')
        }), 201

    except Exception as e:
        return jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500
