from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


@app.route('/', methods=['GET'])
def home():
    return jsonify({"message": "Welcome to the Flask API"}), 200


@app.route('/api/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part in the request'}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        # Process file here
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

# Vercel uses the app directly, so there's no need for if __name__ == '__main__':
