from flask import Flask, request, jsonify
from flask_cors import CORS


app = Flask(__name__)

# CORS setup
CORS(app, resources={
     r"/api/*": {"origins": ["https://portlink-omega.vercel.app"], "methods": ["GET", "POST", "OPTIONS"]}})


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    # Log file information
    print(f"File received: {file.filename}")

    # You can save the file if needed or just process it
    # file.save(f"/path/to/save/{file.filename}")

    return jsonify({
        'message': 'File uploaded successfully!',
        'filename': file.filename,
        'size': len(file.read()),
        'type': file.content_type
    })


if __name__ == '__main__':
    app.run(debug=True)
