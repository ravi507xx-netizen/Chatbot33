from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

@app.route("/prompt=<text>", methods=["GET"])
def proxy(text):
    try:
        api_url = f"https://text.pollinations.ai/prompt/{text}"
        response = requests.get(api_url)

        if response.status_code == 200:
            # return Pollinations API response directly
            return jsonify({
                "status": "success",
                "from_api": response.json()
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Pollinations API error: {response.status_code}"
            }), response.status_code

    except Exception as e:
        return jsonify({
            "status": "failed",
            "error": str(e)
        }), 500

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Pollinations Proxy API working ✅",
        "usage": "/prompt=your_text"
    })

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
