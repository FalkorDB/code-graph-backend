# Use a Python base image
FROM python:3.12

# Set working directory
WORKDIR /api

# Copy requirements.txt and install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port the backend runs on
EXPOSE 5000

# Start the backend
#CMD ["python", "index.py"]
CMD ["flask", "--app", "api/index.py", "run", "--debug"]

