import os
import json
import tempfile
import subprocess
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import requests

# Gemini API Key from environment
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

app = FastAPI()


# ---- MCP Root Endpoint ----
@app.post("/mcp")
async def mcp_handler(request: Request):
    req = await request.json()

    if req.get("method") == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {
                "tools": [
                    {
                        "name": "gh.process_code_with_gemini",
                        "description": "Clone repo, apply find/replace, send to Gemini for code suggestions",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "find_text": {"type": "string"},
                                "replace_text": {"type": "string"},
                                "chatContext": {"type": "object"}
                            },
                            "required": ["find_text", "replace_text", "chatContext"]
                        }
                    }
                ]
            }
        })

    elif req.get("method") == "tools/call":
        tool_name = req["params"]["name"]

        if tool_name == "gh.process_code_with_gemini":
            args = req["params"]["arguments"]
            chat_context = args.get("chatContext", {})

            # ---- Extract repo context ----
            repo_info = chat_context.get("repository", {})
            repo_name = repo_info.get("name")  # "myorg/myrepo"
            branch = repo_info.get("branch", "main")

            file_info = chat_context.get("activeDocument", {})
            file_path = file_info.get("uri", "").replace("file://", "")
            file_content = file_info.get("content", "")

            user_message = chat_context.get("messages", [])[-1]["content"]

            # ---- Clone the repo (GitHub CLI or HTTPS) ----
            tmp_dir = tempfile.mkdtemp()
            repo_url = f"https://github.com/{repo_name}.git"
            subprocess.run(["git", "clone", "--branch", branch, repo_url, tmp_dir], check=True)

            target_file = os.path.join(tmp_dir, os.path.relpath(file_path, "/"))
            updated_content = file_content.replace(args["find_text"], args["replace_text"])

            # ---- Save modified file ----
            os.makedirs(os.path.dirname(target_file), exist_ok=True)
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(updated_content)

            # ---- Build Gemini prompt ----
            prompt = f"""
User request: {user_message}

Repository: {repo_name}, Branch: {branch}
File: {file_path}

Modified content (after find/replace):
{updated_content}

Please analyze and suggest improvements.
"""

            gemini_output = call_gemini(prompt)

            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "result": {
                    "content": [
                        {"type": "text", "text": gemini_output}
                    ]
                }
            })

    # Default: Method not handled
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": req.get("id"),
        "error": {"code": -32601, "message": "Method not found"}
    })


# ---- Gemini API Call ----
def call_gemini(prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ]
    }

    headers = {"Content-Type": "application/json"}
    response = requests.post(url, headers=headers, data=json.dumps(payload))

    if response.status_code == 200:
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    else:
        return f"Gemini API error: {response.text}"
