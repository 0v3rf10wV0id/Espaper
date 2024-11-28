from PIL import Image
import os
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import FileResponse
import uuid
from typing import Dict
from datetime import datetime
import glob

app = FastAPI()

# Create a directory for temporary file storage
UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def create_h_file(xbm_path, h_path):
    # Read the XBM file and skip the header
    with open(xbm_path, 'r') as xbm_file:
        xbm_content = xbm_file.read()
        # Find the start of the actual bitmap data
        data_start = xbm_content.find('{') + 1
        data_end = xbm_content.find('}')
        if data_start == -1 or data_end == -1:
            raise ValueError("Invalid XBM file format")
            
        # Parse the hex values from XBM
        hex_strings = xbm_content[data_start:data_end].strip().split(',')
        data = [int(x.strip(), 16) for x in hex_strings if x.strip()]
    
    # Generate variable name from the output filename
    var_name = os.path.splitext(os.path.basename(h_path))[0].replace('.', '_')
    
    # Create .h file content with binary data formatted as hex
    h_content = f"""#ifndef _{var_name.upper()}_H_
#define _{var_name.upper()}_H_

#define im_width 200
#define im_height 200

static const unsigned char im_bits[] = {{
    {', '.join(f'0x{byte:02x}' for byte in data)}
}};

#endif // _{var_name.upper()}_H_
"""
    
    # Write and validate the .h file
    try:
        with open(h_path, 'w') as h_file:
            h_file.write(h_content)
            
        # Validate structure and content
        with open(h_path, 'r') as h_file:
            content = h_file.read()
            if not all(x in content for x in [
                f"_{var_name.upper()}_H_",
                "im_width",
                "im_height",
                "im_bits[]"
            ]):
                raise ValueError("Generated header file is missing required elements")
            
            # Extract and compare binary data
            h_data_start = content.find('{') + 1
            h_data_end = content.find('}')
            h_hex_strings = content[h_data_start:h_data_end].strip().split(',')
            h_data = [int(x.strip(), 16) for x in h_hex_strings if x.strip()]
            
            # Compare lengths
            if len(data) != len(h_data):
                raise ValueError(f"Data length mismatch: XBM has {len(data)} bytes, .h has {len(h_data)} bytes")
            
            # Compare content
            for i, (xbm_byte, h_byte) in enumerate(zip(data, h_data)):
                if xbm_byte != h_byte:
                    raise ValueError(f"Data mismatch at byte {i}: XBM={xbm_byte:02x}, .h={h_byte:02x}")
                    
    except Exception as e:
        # Remove the invalid file
        os.remove(h_path)
        raise ValueError(f"Header file validation failed: {str(e)}")

def convert_to_xbm(input_image_path, output_xbm_path):
    # Open and resize the image to 200x200
    with Image.open(input_image_path) as img:
        # Convert to RGB if image is in RGBA mode
        if img.mode == 'RGBA':
            img = img.convert('RGB')
            
        # Resize image to 200x200 while maintaining aspect ratio
        img.thumbnail((200, 200), Image.Resampling.LANCZOS)
        
        # Create a new white background image
        background = Image.new('RGB', (200, 200), 'white')
        
        # Calculate position to paste resized image centered
        offset = ((200 - img.size[0]) // 2, (200 - img.size[1]) // 2)
        background.paste(img, offset)
        
        # Convert to black and white
        bw_image = background.convert('1')
        
        # Save as XBM
        bw_image.save(output_xbm_path, 'xbm')

@app.post("/convert")
async def convert_image(file: UploadFile) -> Dict[str, str]:
    # Get base filename without extension
    base_filename = os.path.splitext(file.filename)[0]
    base_path = os.path.join(UPLOAD_DIR, base_filename)
    
    # Save uploaded file
    input_path = f"{base_path}_input{os.path.splitext(file.filename)[1]}"
    with open(input_path, "wb") as f:
        f.write(await file.read())
    
    # Generate output paths
    output_xbm = f"{base_path}.xbm"
    output_h = f"{base_path}.h"
    
    try:
        convert_to_xbm(input_path, output_xbm)
        create_h_file(output_xbm, output_h)
        
        # Return URLs for downloading the files
        return {
            "xbm_url": f"/download/{base_filename}.xbm",
            "h_url": f"/download/{base_filename}.h"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # Clean up input file
        os.remove(input_path)

@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)

@app.get("/latest")
async def get_latest_h_file():
    try:
        # Get all .h files in the upload directory
        h_files = glob.glob(os.path.join(UPLOAD_DIR, "*.h"))
        
        if not h_files:
            raise HTTPException(status_code=404, detail="No converted files found")
            
        # Get the most recently modified file
        latest_file = max(h_files, key=os.path.getmtime)
        
        return FileResponse(
            latest_file,
            media_type="text/plain",
            filename=os.path.basename(latest_file)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Add cleanup function to remove old files (optional)
@app.on_event("startup")
async def cleanup_old_files():
    # Add cleanup logic here if needed
    pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
