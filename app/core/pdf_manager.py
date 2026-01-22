import os
import glob
import hashlib
import json
import google.genai as genai

class PDFManager:
    def __init__(self, pdf_folder, history_file):
        self.pdf_folder = pdf_folder
        self.history_file = history_file
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def _calculate_hash(self, filepath):
        """Calculates the MD5 hash of a file."""
        hasher = hashlib.md5()
        with open(filepath, 'rb') as f:
            buf = f.read()
            hasher.update(buf)
        return hasher.hexdigest()

    def _load_history(self):
        if os.path.exists(self.history_file):
            with open(self.history_file, 'r') as f:
                return json.load(f)
        return {}

    def _save_history(self, history):
        with open(self.history_file, 'w') as f:
            json.dump(history, f, indent=4)

    def sync_pdfs(self):
        """Uploads new or changed PDFs to Gemini, honoring the blacklist."""
        pdf_files = glob.glob(os.path.join(self.pdf_folder, "*.pdf"))
        
        # Load Blacklist
        blacklist = []
        blacklist_file = os.path.join(os.path.dirname(self.history_file), 'blacklist.json')
        if os.path.exists(blacklist_file):
            try:
                with open(blacklist_file, 'r') as f:
                    blacklist = json.load(f)
            except:
                pass

        current_valid_pdfs = []
        for pdf in pdf_files:
            if os.path.basename(pdf) in blacklist:
                print(f"Skipping blacklisted PDF: {os.path.basename(pdf)}")
                continue
            current_valid_pdfs.append(pdf)
            
        return current_valid_pdfs

    def upload_for_session(self, pdf_paths):
        """Uploads the specified PDFs for immediate use in a generation session."""
        uploaded_refs = []
        print(f"Uploading {len(pdf_paths)} PDFs...")
        for pdf in pdf_paths:
            # Check if file exists
            if not os.path.exists(pdf):
                continue
            
            # Create a user-displayable name
            display_name = os.path.basename(pdf)
            
            with open(pdf, 'rb') as f:
                # Upload to Gemini
                # Note: This returns a File object that can be passed to generate_content
                uploaded_file = self.client.files.upload(file=f)
                uploaded_refs.append(uploaded_file)
        
        print("Upload complete.")
        return uploaded_refs
