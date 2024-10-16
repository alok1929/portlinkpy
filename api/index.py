from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
import traceback


app = Flask(__name__)

# CORS setup
CORS(app, resources={
     r"/api/*": {"origins": ["https://portlink-omega.vercel.app"], "methods": ["GET", "POST", "OPTIONS"]}})


@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part in the request'}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        # Log file information
        print(f"File received: {file.filename}")

        # Read the file content
        file_content = file.read()

        # You can process the file content here if needed
        # For example, you could save it to a cloud storage service

        return jsonify({
            'message': 'File uploaded successfully!',
            'filename': file.filename,
            'size': len(file_content),
            'type': file.content_type
        })
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    print(f"Unhandled Exception: {str(e)}")
    print(traceback.format_exc())
    return jsonify(error=str(e)), 500


@app.route('/')
def home():
    return "Flask server is running!"
