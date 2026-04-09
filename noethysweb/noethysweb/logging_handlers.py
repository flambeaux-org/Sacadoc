import logging
import requests
import traceback

class GithubLoggingHandler(logging.Handler):
    def __init__(self, token, repo_owner, repo_name):
        super().__init__()
        self.token = token
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.sensitive_keywords = r'(password|secret|token|key|authorization|api_key)'

    def sanitize_data(self, text):
        """
        Looks for sensitive keywords followed by an equals sign, colon, 
        or space, and masks the value that follows it.
        """
        if not text:
            return text
            
        # Regex to find: keyword + (separator like =, :, or space) + (the secret value)
        pattern = re.compile(rf'(?i)({self.sensitive_keywords}[\s:=]+)([^\s&\'"]+)')
        
        # Replace the secret value with asterisks
        sanitized_text = pattern.sub(r'\1********', text)
        return sanitized_text

    def emit(self, record):
        if not record.exc_info:
            return
            
        exc_type, exc_value, exc_traceback = record.exc_info
        
        error_type_name = exc_type.__name__
        raw_title_msg = str(exc_value)[:60]
        safe_title_msg = self.sanitize_data(raw_title_msg)
        title = f"Automated 500: {error_type_name} - {safe_title_msg}"
        
        request_path = "Unknown"
        if hasattr(record, 'request'):
            request_path = f"{record.request.method} {record.request.path}"

        raw_tb = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        safe_tb = self.sanitize_data(raw_tb)
        
        body = (
            f"> ⚠️ **ATTENTION ÉQUIPE DEV** ⚠️\n"
            f"> **Si vous prenez en charge cette issue, veuillez vous l'attribuer (Assignees) ou mettre une réaction (👀 ou 🛠️) sur ce message.** Cela évitera que nous fassions le travail en double !\n\n"
            f"---\n\n"
            f"**An automated 500 error was caught.**\n\n"
            f"**Endpoint:** `{request_path}`\n\n"
            f"<details><summary><b>Click to view Traceback</b></summary>\n\n"
            f"```python\n{safe_tb}\n```\n"
            f"</details>"
        )

        try:
            # 1. DEDUPLICATION CHECK
            search_query = f"repo:{self.repo_owner}/{self.repo_name} is:issue is:open in:title \"{error_type_name}\""
            search_url = f"https://api.github.com/search/issues?q={search_query}"
            
            search_res = requests.get(search_url, headers=self.headers, timeout=5)
            if search_res.status_code == 200:
                data = search_res.json()
                if data.get("total_count", 0) > 0:
                    # An open issue already exists for this error. We silently exit.
                    return
            
            # 2. CREATE THE ISSUE
            issue_url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/issues"
            payload = {
                "title": title,
                "body": body,
                "labels": ["bug", "automated-500"]
            }
            requests.post(issue_url, json=payload, headers=self.headers, timeout=5)
            
        except Exception:
            # Failsafe: If GitHub is down, we DO NOT want to crash our own server.
            # Catch all exceptions during logging and pass silently.
            pass
