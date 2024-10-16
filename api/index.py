from flask import Flask, request, jsonify
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)


@app.route('/api/upload', methods=['POST'])
def upload_file():
    print("Received upload request")
    print(f"Request method: {request.method}")
    print(f"Request headers: {request.headers}")
    print(f"Request files: {request.files}")
    print(f"Request form: {request.form}")

    try:
        if 'file' not in request.files:
            print("No file part in the request")
            return jsonify({'error': 'No file part in the request'}), 400

        file = request.files['file']

        if file.filename == '':
            print("No selected file")
            return jsonify({'error': 'No selected file'}), 400

        print(f"File received: {file.filename}")

        file_content = file.read()

        return jsonify({
            'message': 'File uploaded successfully!',
            'filename': file.filename,
            'size': len(file_content),
            'type': file.content_type
        })
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy'}), 200


# This is only used when running locally. Vercel uses the `app` directly.
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
