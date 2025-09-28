FROM ubuntu:22.04

# Install required packages for building libpostal and Python, plus fastapi and uvicorn
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    autoconf \
    automake \
    libtool \
    pkg-config \
    sudo \
    wget \
    curl \
    python3 \
    python3-pip \
    python3-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Clone the libpostal repository
RUN git clone https://github.com/openvenues/libpostal.git /libpostal

RUN if [ -f Makefile ]; then make distclean; fi


# Create __init__.py file inside the libpostal folder to mark as Python package
RUN touch /libpostal/__init__.py

# Copy scrapping.py into the libpostal directory
COPY scrapping.py /libpostal/scrapping.py

# Set working directory inside the libpostal folder
WORKDIR /libpostal

# Create directory for libpostal data
RUN mkdir -p /usr/local/share/libpostal

# Run bootstrap.sh to generate configure script
RUN ./bootstrap.sh

# Configure - choose the appropriate one by uncommenting
RUN ./configure --datadir=/usr/local/share/libpostal
# RUN ./configure --datadir=/usr/local/share/libpostal --disable-sse2
# RUN ./configure --datadir=/usr/local/share/libpostal MODEL=senzing

# Build and install libpostal
RUN make -j4 || make
RUN sudo make install
RUN sudo ldconfig

# Install the Python bindings for libpostal
WORKDIR /


COPY requirements.txt .
COPY main.py .
COPY templates ./templates

RUN pip3 install -r requirements.txt

# Expose FastAPI default port
EXPOSE 8000

# Command to run FastAPI app in development mode using uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

