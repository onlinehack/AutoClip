import os
import sys

def main():
    """
    Launch the Streamlit UI for AutoClip.
    """
    print("Launching AutoClip Studio UI...")
    # Use os.system to run the streamlit command
    # This assumes streamlit is installed and in the path, which it should be based on requirements.
    exit_code = os.system("streamlit run gui_app.py")
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
