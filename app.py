from flask import Flask, request, Response
import requests

app = Flask(__name__)

@app.route("/prompt=<text>", methods=["GET"])
def proxy(text):
    try:
        api_url = f"https://text.pollinations.ai/prompt/{text}?model=openai-audio&voice=verse"
        resp = requests.get(api_url, stream=True)

        # Detect content type
        content_type = resp.headers.get("Content-Type", "")

        return Response(
            resp.content,
            status=resp.status_code,
            content_type=content_type
        )

    except Exception as e:
        return {"status": "failed", "error": str(e)}, 500

@app.route("/", methods=["GET"])
def home():
    return {"message": "Pollinations Proxy API working ✅", "usage": "/prompt=your_text"}

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
