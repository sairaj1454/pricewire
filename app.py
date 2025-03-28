from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'temp_uploads'

# Create upload folder at startup
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def ensure_upload_folder():
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

def clean_value(value):
    if pd.isna(value):
        return ''
    value = str(value).strip()
    # Convert common variations of empty/zero values
    if value.lower() in ['nan', 'std', 'n/c', '0', '', '-']:
        return '0'
    return value

def get_row_key(row):
    """Create a unique key for a row based on its values."""
    return tuple(str(row.get(col, '')).strip().lower() for col in ['Description', 'Code', 'WSD', 'Dealer Invoice', 'Retail Price'])

def process_excel_files(file1, file2):
    ensure_upload_folder()
    
    # Save files temporarily
    file1_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file1.filename))
    file2_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file2.filename))
    file1.save(file1_path)
    file2.save(file2_path)
    
    try:
        # Read Excel files starting from row 12 (0-based index 11)
        df1 = pd.read_excel(file1_path, header=11, dtype=str)
        df2 = pd.read_excel(file2_path, header=11, dtype=str)
        
        # Clean column names
        df1.columns = [str(col).strip() for col in df1.columns]
        df2.columns = [str(col).strip() for col in df2.columns]
        
        # Define columns to compare with correct names
        columns = ['Description', 'Code', 'WSD', 'Dealer Invoice', 'Retail Price']
        
        # Create comparison results
        comparison_results = []
        
        # Get all unique codes while preserving order from df1 (old transit file)
        codes_df1 = pd.unique(df1['Code'].dropna()).tolist()
        codes_df2 = df2['Code'].dropna().unique().tolist()
        
        # Start with codes from df1 (maintaining their order)
        all_codes = codes_df1.copy()
        # Add any new codes from df2 that aren't in df1
        all_codes.extend([code for code in codes_df2 if code not in codes_df1])
        
        for code in all_codes:
            # Get rows with matching code
            rows1 = df1[df1['Code'].astype(str) == str(code)]
            rows2 = df2[df2['Code'].astype(str) == str(code)]
            
            # Convert to list of dictionaries and remove duplicates
            rows1_list = [row.to_dict() for _, row in rows1.iterrows()]
            rows2_list = [row.to_dict() for _, row in rows2.iterrows()]
            
            # Remove duplicates while preserving order
            seen1 = set()
            seen2 = set()
            unique_rows1 = []
            unique_rows2 = []
            
            for row in rows1_list:
                key = get_row_key(row)
                if key not in seen1:
                    seen1.add(key)
                    unique_rows1.append(row)
            
            for row in rows2_list:
                key = get_row_key(row)
                if key not in seen2:
                    seen2.add(key)
                    unique_rows2.append(row)
            
            # Compare each row
            max_rows = max(len(unique_rows1), len(unique_rows2))
            for idx in range(max_rows):
                row1 = unique_rows1[idx] if idx < len(unique_rows1) else None
                row2 = unique_rows2[idx] if idx < len(unique_rows2) else None
                
                result = {
                    'Description_File1': str(row1.get('Description', '')) if row1 else '',
                    'Description_File2': str(row2.get('Description', '')) if row2 else '',
                    'Code': str(code),
                    'WSD_Price_File1': str(row1.get('WSD', '')) if row1 else '',
                    'WSD_Price_File2': str(row2.get('WSD', '')) if row2 else '',
                    'Dealer_Invoice_File1': str(row1.get('Dealer Invoice', '')) if row1 else '',
                    'Dealer_Invoice_File2': str(row2.get('Dealer Invoice', '')) if row2 else '',
                    'Retail_Price_File1': str(row1.get('Retail Price', '')) if row1 else '',
                    'Retail_Price_File2': str(row2.get('Retail Price', '')) if row2 else ''
                }
                
                # Calculate differences
                result['Description_Different'] = result['Description_File1'] != result['Description_File2']
                result['Code_Different'] = False  # Code is the matching key
                result['WSD_Different'] = clean_value(result['WSD_Price_File1']) != clean_value(result['WSD_Price_File2'])
                result['Invoice_Different'] = clean_value(result['Dealer_Invoice_File1']) != clean_value(result['Dealer_Invoice_File2'])
                result['Price_Different'] = clean_value(result['Retail_Price_File1']) != clean_value(result['Retail_Price_File2'])
                
                # Add change status
                result['Status'] = 'CHANGE' if any([
                    result['Description_Different'],
                    result['WSD_Different'],
                    result['Invoice_Different'],
                    result['Price_Different']
                ]) else 'NO CHANGE'
                
                comparison_results.append(result)
        
        return comparison_results
    
    finally:
        # Clean up temporary files
        if os.path.exists(file1_path):
            os.remove(file1_path)
        if os.path.exists(file2_path):
            os.remove(file2_path)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/compare', methods=['POST'])
def compare():
    if 'file1' not in request.files or 'file2' not in request.files:
        return jsonify({'error': 'Both files are required'})
    
    file1 = request.files['file1']
    file2 = request.files['file2']
    
    if file1.filename == '' or file2.filename == '':
        return jsonify({'error': 'Both files are required'})
    
    try:
        results = process_excel_files(file1, file2)
        return jsonify({'results': results})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/update_template', methods=['POST'])
def update_template():
    if 'old_template' not in request.files:
        return jsonify({'error': 'Template file is required'})
    
    old_template = request.files['old_template']
    new_data = request.json.get('new_data', [])
    
    if old_template.filename == '':
        return jsonify({'error': 'Template file is required'})
    
    try:
        ensure_upload_folder()
        template_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(old_template.filename))
        old_template.save(template_path)
        
        # Read the template preserving all formatting
        df = pd.read_excel(template_path, header=None)
        
        # Find the data start row
        start_row = None
        for idx, row in df.iterrows():
            if str(row[0]).strip() == "BASE VEHICLE":
                start_row = idx + 1
                break
        
        if start_row is None:
            raise ValueError("Could not find 'BASE VEHICLE' in the template")
        
        # Get the headers
        headers = df.iloc[start_row-1]
        
        # Update the template with new data
        for item in new_data:
            code = item['Code']
            mask = df.iloc[start_row:][df.iloc[start_row:][2] == code].index
            if len(mask) > 0:
                df.loc[mask, 1] = item['Description_File2']  # Description
                df.loc[mask, 3] = item['WSD_Price_File2']    # WSD Price
                df.loc[mask, 4] = item['Dealer_Invoice_File2']  # Dealer Invoice
                df.loc[mask, 5] = item['Retail_Price_File2']    # Retail Price
        
        # Save the updated template
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], 'updated_' + secure_filename(old_template.filename))
        df.to_excel(output_path, index=False, header=False)
        
        # Return the file for download
        return send_file(output_path, as_attachment=True, download_name='updated_template.xlsx')
    
    except Exception as e:
        return jsonify({'error': str(e)})
    finally:
        # Clean up temporary files
        if os.path.exists(template_path):
            os.remove(template_path)
        if os.path.exists(output_path):
            os.remove(output_path)

if __name__ == '__main__':
    # For local development
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
