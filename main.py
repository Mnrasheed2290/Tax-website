import os
import io
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, flash, redirect, url_for, jsonify
from werkzeug.utils import secure_filename
import pandas as pd
import fitz  # PyMuPDF
from PIL import Image
import pytesseract
import re

# Configure logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "numeral-sales-tax-2025")

# Configuration
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size
app.config['UPLOAD_EXTENSIONS'] = ['.csv', '.xlsx', '.xls', '.pdf', '.png', '.jpg', '.jpeg']
app.config['UPLOAD_FOLDER'] = 'uploads'

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Product tax rules by state (simplified)
PRODUCT_TAX_RULES = {
    'software': {
        'CA': {'taxable': True, 'rate_modifier': 1.0},
        'NY': {'taxable': True, 'rate_modifier': 1.0},
        'TX': {'taxable': True, 'rate_modifier': 1.0},
        'FL': {'taxable': True, 'rate_modifier': 1.0},
        'IL': {'taxable': True, 'rate_modifier': 1.0},
        'WA': {'taxable': True, 'rate_modifier': 1.0},
        'GA': {'taxable': True, 'rate_modifier': 1.0},
        'NC': {'taxable': True, 'rate_modifier': 1.0}
    },
    'saas': {
        'CA': {'taxable': True, 'rate_modifier': 1.0},
        'NY': {'taxable': True, 'rate_modifier': 1.0},
        'TX': {'taxable': True, 'rate_modifier': 1.0},
        'FL': {'taxable': False, 'rate_modifier': 0.0},
        'IL': {'taxable': True, 'rate_modifier': 1.0},
        'WA': {'taxable': True, 'rate_modifier': 1.0},
        'GA': {'taxable': False, 'rate_modifier': 0.0},
        'NC': {'taxable': True, 'rate_modifier': 1.0}
    },
    'physical_goods': {
        'CA': {'taxable': True, 'rate_modifier': 1.0},
        'NY': {'taxable': True, 'rate_modifier': 1.0},
        'TX': {'taxable': True, 'rate_modifier': 1.0},
        'FL': {'taxable': True, 'rate_modifier': 1.0},
        'IL': {'taxable': True, 'rate_modifier': 1.0},
        'WA': {'taxable': True, 'rate_modifier': 1.0},
        'GA': {'taxable': True, 'rate_modifier': 1.0},
        'NC': {'taxable': True, 'rate_modifier': 1.0}
    },
    'consulting': {
        'CA': {'taxable': False, 'rate_modifier': 0.0},
        'NY': {'taxable': False, 'rate_modifier': 0.0},
        'TX': {'taxable': True, 'rate_modifier': 1.0},
        'FL': {'taxable': False, 'rate_modifier': 0.0},
        'IL': {'taxable': False, 'rate_modifier': 0.0},
        'WA': {'taxable': True, 'rate_modifier': 1.0},
        'GA': {'taxable': False, 'rate_modifier': 0.0},
        'NC': {'taxable': False, 'rate_modifier': 0.0}
    }
}

# Local tax rates by major cities (simplified dataset)
LOCAL_TAX_RATES = {
    'CA': {
        'Los Angeles': {'city': 0.005, 'county': 0.0025, 'district': 0.0075},
        'San Francisco': {'city': 0.00875, 'county': 0.0025, 'district': 0.00125},
        'San Diego': {'city': 0.005, 'county': 0.0025, 'district': 0.005},
        'Sacramento': {'city': 0.00875, 'county': 0.0025, 'district': 0.00875},
        'Oakland': {'city': 0.00875, 'county': 0.0025, 'district': 0.00125}
    },
    'NY': {
        'New York': {'city': 0.045, 'county': 0.00375, 'district': 0.00125},
        'Buffalo': {'city': 0.03, 'county': 0.0025, 'district': 0.005},
        'Rochester': {'city': 0.035, 'county': 0.003, 'district': 0.004},
        'Syracuse': {'city': 0.04, 'county': 0.0025, 'district': 0.003}
    },
    'TX': {
        'Houston': {'city': 0.0125, 'county': 0.0025, 'district': 0.01},
        'Dallas': {'city': 0.0125, 'county': 0.0025, 'district': 0.0075},
        'Austin': {'city': 0.0125, 'county': 0.0075, 'district': 0.005},
        'San Antonio': {'city': 0.0125, 'county': 0.00125, 'district': 0.00625}
    },
    'FL': {
        'Miami': {'city': 0.0075, 'county': 0.0075, 'district': 0.001},
        'Orlando': {'city': 0.0075, 'county': 0.0065, 'district': 0.005},
        'Tampa': {'city': 0.025, 'county': 0.0075, 'district': 0.001},
        'Jacksonville': {'city': 0.0075, 'county': 0.00625, 'district': 0.005}
    },
    'IL': {
        'Chicago': {'city': 0.0125, 'county': 0.0075, 'district': 0.025},
        'Rockford': {'city': 0.00875, 'county': 0.0075, 'district': 0.01},
        'Peoria': {'city': 0.01, 'county': 0.0075, 'district': 0.0025}
    },
    'WA': {
        'Seattle': {'city': 0.0035, 'county': 0.0015, 'district': 0.0275},
        'Spokane': {'city': 0.028, 'county': 0.003, 'district': 0.003},
        'Tacoma': {'city': 0.028, 'county': 0.003, 'district': 0.006}
    }
}

# US States with sales tax requirements
US_STATES = {
    'AL': {'name': 'Alabama', 'rate': 0.04, 'nexus_threshold': 250000},
    'AK': {'name': 'Alaska', 'rate': 0.00, 'nexus_threshold': 100000},
    'AZ': {'name': 'Arizona', 'rate': 0.056, 'nexus_threshold': 200000},
    'AR': {'name': 'Arkansas', 'rate': 0.065, 'nexus_threshold': 100000},
    'CA': {'name': 'California', 'rate': 0.0725, 'nexus_threshold': 500000},
    'CO': {'name': 'Colorado', 'rate': 0.029, 'nexus_threshold': 100000},
    'CT': {'name': 'Connecticut', 'rate': 0.0635, 'nexus_threshold': 250000},
    'DE': {'name': 'Delaware', 'rate': 0.00, 'nexus_threshold': 0},
    'FL': {'name': 'Florida', 'rate': 0.06, 'nexus_threshold': 100000},
    'GA': {'name': 'Georgia', 'rate': 0.04, 'nexus_threshold': 100000},
    'HI': {'name': 'Hawaii', 'rate': 0.04, 'nexus_threshold': 100000},
    'ID': {'name': 'Idaho', 'rate': 0.06, 'nexus_threshold': 100000},
    'IL': {'name': 'Illinois', 'rate': 0.0625, 'nexus_threshold': 100000},
    'IN': {'name': 'Indiana', 'rate': 0.07, 'nexus_threshold': 100000},
    'IA': {'name': 'Iowa', 'rate': 0.06, 'nexus_threshold': 100000},
    'KS': {'name': 'Kansas', 'rate': 0.065, 'nexus_threshold': 100000},
    'KY': {'name': 'Kentucky', 'rate': 0.06, 'nexus_threshold': 100000},
    'LA': {'name': 'Louisiana', 'rate': 0.0445, 'nexus_threshold': 100000},
    'ME': {'name': 'Maine', 'rate': 0.055, 'nexus_threshold': 100000},
    'MD': {'name': 'Maryland', 'rate': 0.06, 'nexus_threshold': 100000},
    'MA': {'name': 'Massachusetts', 'rate': 0.0625, 'nexus_threshold': 100000},
    'MI': {'name': 'Michigan', 'rate': 0.06, 'nexus_threshold': 100000},
    'MN': {'name': 'Minnesota', 'rate': 0.06875, 'nexus_threshold': 100000},
    'MS': {'name': 'Mississippi', 'rate': 0.07, 'nexus_threshold': 250000},
    'MO': {'name': 'Missouri', 'rate': 0.04225, 'nexus_threshold': 100000},
    'MT': {'name': 'Montana', 'rate': 0.00, 'nexus_threshold': 0},
    'NE': {'name': 'Nebraska', 'rate': 0.055, 'nexus_threshold': 100000},
    'NV': {'name': 'Nevada', 'rate': 0.0685, 'nexus_threshold': 100000},
    'NH': {'name': 'New Hampshire', 'rate': 0.00, 'nexus_threshold': 0},
    'NJ': {'name': 'New Jersey', 'rate': 0.06625, 'nexus_threshold': 100000},
    'NM': {'name': 'New Mexico', 'rate': 0.05125, 'nexus_threshold': 100000},
    'NY': {'name': 'New York', 'rate': 0.08, 'nexus_threshold': 500000},
    'NC': {'name': 'North Carolina', 'rate': 0.0475, 'nexus_threshold': 100000},
    'ND': {'name': 'North Dakota', 'rate': 0.05, 'nexus_threshold': 100000},
    'OH': {'name': 'Ohio', 'rate': 0.0575, 'nexus_threshold': 100000},
    'OK': {'name': 'Oklahoma', 'rate': 0.045, 'nexus_threshold': 100000},
    'OR': {'name': 'Oregon', 'rate': 0.00, 'nexus_threshold': 0},
    'PA': {'name': 'Pennsylvania', 'rate': 0.06, 'nexus_threshold': 100000},
    'RI': {'name': 'Rhode Island', 'rate': 0.07, 'nexus_threshold': 100000},
    'SC': {'name': 'South Carolina', 'rate': 0.06, 'nexus_threshold': 100000},
    'SD': {'name': 'South Dakota', 'rate': 0.045, 'nexus_threshold': 100000},
    'TN': {'name': 'Tennessee', 'rate': 0.07, 'nexus_threshold': 100000},
    'TX': {'name': 'Texas', 'rate': 0.0625, 'nexus_threshold': 500000},
    'UT': {'name': 'Utah', 'rate': 0.0485, 'nexus_threshold': 100000},
    'VT': {'name': 'Vermont', 'rate': 0.06, 'nexus_threshold': 100000},
    'VA': {'name': 'Virginia', 'rate': 0.053, 'nexus_threshold': 100000},
    'WA': {'name': 'Washington', 'rate': 0.065, 'nexus_threshold': 100000},
    'WV': {'name': 'West Virginia', 'rate': 0.06, 'nexus_threshold': 100000},
    'WI': {'name': 'Wisconsin', 'rate': 0.05, 'nexus_threshold': 100000},
    'WY': {'name': 'Wyoming', 'rate': 0.04, 'nexus_threshold': 100000}
}

def validate_file(filename):
    """Validate file extension and return file type"""
    if not filename:
        return None, "No file selected"
    
    ext = os.path.splitext(filename)[1].lower()
    if ext not in app.config['UPLOAD_EXTENSIONS']:
        return None, f"Invalid file type. Allowed: {', '.join(app.config['UPLOAD_EXTENSIONS'])}"
    
    return ext, None

def classify_product(product_description):
    """Classify product based on description"""
    if not product_description:
        return 'physical_goods'
    
    product_lower = product_description.lower()
    
    if any(keyword in product_lower for keyword in ['software', 'license', 'app']):
        return 'software'
    elif any(keyword in product_lower for keyword in ['saas', 'subscription', 'service', 'platform']):
        return 'saas'
    elif any(keyword in product_lower for keyword in ['consulting', 'development', 'custom', 'professional']):
        return 'consulting'
    else:
        return 'physical_goods'

def is_product_taxable(product_type, state_code):
    """Check if product is taxable in a given state"""
    if product_type in PRODUCT_TAX_RULES and state_code in PRODUCT_TAX_RULES[product_type]:
        return PRODUCT_TAX_RULES[product_type][state_code]['taxable']
    return True  # Default to taxable

def get_local_tax_rates(state_code, city_name):
    """Get local tax rates for a specific city and state"""
    if state_code in LOCAL_TAX_RATES and city_name in LOCAL_TAX_RATES[state_code]:
        local_rates = LOCAL_TAX_RATES[state_code][city_name]
        return {
            'city_rate': local_rates['city'],
            'county_rate': local_rates['county'],
            'district_rate': local_rates['district'],
            'total_local_rate': local_rates['city'] + local_rates['county'] + local_rates['district']
        }
    return {
        'city_rate': 0.0,
        'county_rate': 0.0,
        'district_rate': 0.0,
        'total_local_rate': 0.0
    }

def analyze_sales_data_csv(file_stream):
    """Analyze sales data from CSV files for tax compliance"""
    try:
        df = pd.read_csv(file_stream)
        
        # Identify common column patterns
        amount_cols = [col for col in df.columns if any(keyword in col.lower() for keyword in ['amount', 'total', 'price', 'sales', 'revenue'])]
        state_cols = [col for col in df.columns if any(keyword in col.lower() for keyword in ['state', 'region', 'location'])]
        date_cols = [col for col in df.columns if any(keyword in col.lower() for keyword in ['date', 'time', 'created'])]
        address_cols = [col for col in df.columns if any(keyword in col.lower() for keyword in ['address', 'street', 'city', 'zip', 'postal'])]
        city_cols = [col for col in df.columns if any(keyword in col.lower() for keyword in ['city', 'municipality'])]
        county_cols = [col for col in df.columns if any(keyword in col.lower() for keyword in ['county', 'parish'])]
        product_cols = [col for col in df.columns if any(keyword in col.lower() for keyword in ['product', 'item', 'description', 'type', 'category'])]
        
        # Calculate sales tax analysis with product-based taxability
        nexus_analysis = analyze_nexus_threshold(df, amount_cols, state_cols, city_cols)
        tax_obligations = calculate_tax_obligations_by_product(df, amount_cols, state_cols, city_cols, product_cols)
        compliance_status = check_compliance_status(nexus_analysis)
        
        # Generate filing requirements
        filing_requirements = generate_filing_requirements(nexus_analysis)
        
        return {
            'type': 'sales_data',
            'summary': {
                'total_transactions': len(df),
                'total_revenue': sum([df[col].sum() for col in amount_cols if col in df.columns]),
                'states_with_sales': len(nexus_analysis),
                'nexus_states': len([state for state, data in nexus_analysis.items() if data['has_nexus']]),
                'filing_required': len(filing_requirements)
            },
            'nexus_analysis': nexus_analysis,
            'tax_obligations': tax_obligations,
            'compliance_status': compliance_status,
            'filing_requirements': filing_requirements,
            'preview': df.head(10).to_dict('records') if len(df) > 0 else [],
            'success': True
        }
        
    except Exception as e:
        logging.error(f"Sales data analysis error: {str(e)}")
        return {
            'type': 'sales_data',
            'error': f"Error analyzing sales data: {str(e)}",
            'success': False
        }

def analyze_nexus_threshold(df, amount_cols, state_cols, city_cols=None):
    """Analyze if sales meet nexus thresholds in each state with local tax rates"""
    nexus_analysis = {}
    
    if not state_cols or not amount_cols:
        return nexus_analysis
    
    state_col = state_cols[0]
    amount_col = amount_cols[0]
    city_col = city_cols[0] if city_cols and len(city_cols) > 0 else None
    
    # Group sales by state (and city if available)
    if city_col and city_col in df.columns:
        grouped_sales = df.groupby([state_col, city_col])[amount_col].sum() if state_col in df.columns and amount_col in df.columns else {}
    else:
        grouped_sales = df.groupby(state_col)[amount_col].sum() if state_col in df.columns and amount_col in df.columns else {}
    
    # Aggregate by state for nexus analysis
    state_totals = {}
    local_tax_details = {}
    
    for key, sales_amount in grouped_sales.items():
        if isinstance(key, tuple):  # State and city
            state_code, city_name = key
            state_code = str(state_code).upper()
            city_name = str(city_name).title()
            
            if state_code not in state_totals:
                state_totals[state_code] = 0
                local_tax_details[state_code] = []
            
            state_totals[state_code] += sales_amount
            
            # Get local tax rates for this city
            local_rates = get_local_tax_rates(state_code, city_name)
            local_tax_details[state_code].append({
                'city': city_name,
                'sales': sales_amount,
                'local_rates': local_rates
            })
        else:  # Just state
            state_code = str(key).upper()
            state_totals[state_code] = sales_amount
            local_tax_details[state_code] = []
    
    for state_code, total_sales in state_totals.items():
        if state_code in US_STATES:
            threshold = US_STATES[state_code]['nexus_threshold']
            has_nexus = total_sales >= threshold if threshold > 0 else False
            
            # Calculate average local tax rate weighted by sales
            total_local_rate = 0
            total_local_sales = 0
            city_breakdown = local_tax_details.get(state_code, [])
            
            for city_data in city_breakdown:
                city_sales = city_data['sales']
                city_local_rate = city_data['local_rates']['total_local_rate']
                total_local_rate += city_local_rate * city_sales
                total_local_sales += city_sales
            
            avg_local_rate = total_local_rate / total_local_sales if total_local_sales > 0 else 0
            combined_rate = US_STATES[state_code]['rate'] + avg_local_rate
            
            nexus_analysis[state_code] = {
                'state_name': US_STATES[state_code]['name'],
                'total_sales': total_sales,
                'nexus_threshold': threshold,
                'has_nexus': has_nexus,
                'excess_amount': max(0, total_sales - threshold) if threshold > 0 else 0,
                'state_tax_rate': US_STATES[state_code]['rate'],
                'avg_local_tax_rate': avg_local_rate,
                'combined_tax_rate': combined_rate,
                'city_breakdown': city_breakdown
            }
    
    return nexus_analysis

def calculate_tax_obligations_by_product(df, amount_cols, state_cols, city_cols=None, product_cols=None):
    """Calculate tax obligations by product type for each state including local taxes"""
    tax_obligations = {}
    
    if not state_cols or not amount_cols:
        return tax_obligations
    
    state_col = state_cols[0]
    amount_col = amount_cols[0]
    city_col = city_cols[0] if city_cols and len(city_cols) > 0 else None
    product_col = product_cols[0] if product_cols and len(product_cols) > 0 else None
    
    # Add product classification column
    if product_col and product_col in df.columns:
        df['product_type'] = df[product_col].apply(classify_product)
    else:
        df['product_type'] = 'physical_goods'
    
    # Group by state, city (if available), and product type
    group_cols = [state_col, 'product_type']
    if city_col and city_col in df.columns:
        group_cols.insert(1, city_col)
    
    grouped_sales = df.groupby(group_cols)[amount_col].sum() if all(col in df.columns for col in group_cols) else {}
    
    # Aggregate by state for tax calculations
    state_details = {}
    
    for key, sales_amount in grouped_sales.items():
        if len(group_cols) == 3:  # State, city, product
            state_code, city_name, product_type = key
            city_name = str(city_name).title()
        else:  # State, product
            state_code, product_type = key
            city_name = None
        
        state_code = str(state_code).upper()
        
        if state_code not in state_details:
            state_details[state_code] = {
                'total_sales': 0,
                'taxable_sales': 0,
                'state_tax_owed': 0,
                'local_tax_owed': 0,
                'product_breakdown': {},
                'city_breakdown': []
            }
        
        # Check if product is taxable in this state
        is_taxable = is_product_taxable(product_type, state_code)
        
        state_details[state_code]['total_sales'] += sales_amount
        
        if is_taxable:
            state_details[state_code]['taxable_sales'] += sales_amount
            
            # Calculate taxes
            if state_code in US_STATES:
                state_tax_rate = US_STATES[state_code]['rate']
                state_tax = sales_amount * state_tax_rate
                state_details[state_code]['state_tax_owed'] += state_tax
                
                # Calculate local taxes if city available
                if city_name:
                    local_rates = get_local_tax_rates(state_code, city_name)
                    local_tax = sales_amount * local_rates['total_local_rate']
                    state_details[state_code]['local_tax_owed'] += local_tax
                    
                    # Track city breakdown
                    state_details[state_code]['city_breakdown'].append({
                        'city': city_name,
                        'product_type': product_type,
                        'sales': sales_amount,
                        'taxable': is_taxable,
                        'state_tax': state_tax,
                        'local_tax': local_tax,
                        'local_rates': local_rates
                    })
        
        # Track product breakdown
        if product_type not in state_details[state_code]['product_breakdown']:
            state_details[state_code]['product_breakdown'][product_type] = {
                'total_sales': 0,
                'taxable_sales': 0,
                'tax_owed': 0,
                'is_taxable': is_taxable
            }
        
        state_details[state_code]['product_breakdown'][product_type]['total_sales'] += sales_amount
        if is_taxable:
            state_details[state_code]['product_breakdown'][product_type]['taxable_sales'] += sales_amount
            if state_code in US_STATES:
                product_tax = sales_amount * US_STATES[state_code]['rate']
                if city_name:
                    local_rates = get_local_tax_rates(state_code, city_name)
                    product_tax += sales_amount * local_rates['total_local_rate']
                state_details[state_code]['product_breakdown'][product_type]['tax_owed'] += product_tax
    
    # Format final results
    for state_code, details in state_details.items():
        if state_code in US_STATES:
            total_tax_owed = details['state_tax_owed'] + details['local_tax_owed']
            
            tax_obligations[state_code] = {
                'state_name': US_STATES[state_code]['name'],
                'total_sales': details['total_sales'],
                'taxable_sales': details['taxable_sales'],
                'non_taxable_sales': details['total_sales'] - details['taxable_sales'],
                'state_tax_rate': US_STATES[state_code]['rate'],
                'state_tax_owed': details['state_tax_owed'],
                'local_tax_owed': details['local_tax_owed'],
                'total_tax_owed': total_tax_owed,
                'product_breakdown': details['product_breakdown'],
                'city_breakdown': details['city_breakdown']
            }
    
    return tax_obligations

def check_compliance_status(nexus_analysis):
    """Check compliance status based on nexus analysis"""
    total_states = len(nexus_analysis)
    nexus_states = len([state for state, data in nexus_analysis.items() if data['has_nexus']])
    non_compliant = nexus_states  # Assuming all nexus states need registration
    
    return {
        'total_states': total_states,
        'nexus_states': nexus_states,
        'registered_states': 0,  # Would come from user configuration
        'non_compliant_states': non_compliant,
        'compliance_percentage': 0 if nexus_states == 0 else 0  # Would be calculated based on registrations
    }

def generate_filing_requirements(nexus_analysis):
    """Generate filing requirements for states with nexus"""
    filing_requirements = []
    
    for state_code, data in nexus_analysis.items():
        # Only generate filing requirements for states that have reached nexus threshold
        if data['has_nexus'] and data['nexus_threshold'] > 0:
            # Determine filing frequency based on sales volume
            if data['total_sales'] > 500000:
                frequency = 'Monthly'
            elif data['total_sales'] > 250000:
                frequency = 'Quarterly'
            else:
                frequency = 'Annual'
            
            # Calculate next due date based on frequency
            if frequency == 'Monthly':
                next_due = datetime.now() + timedelta(days=20)
            elif frequency == 'Quarterly':
                next_due = datetime.now() + timedelta(days=45)
            else:
                next_due = datetime.now() + timedelta(days=90)
            
            filing_requirements.append({
                'state_code': state_code,
                'state_name': data['state_name'],
                'frequency': frequency,
                'next_due_date': next_due.strftime('%Y-%m-%d'),
                'estimated_tax': data['total_sales'] * data.get('combined_tax_rate', data.get('state_tax_rate', 0)),
                'status': 'Registration & Filing Required',
                'priority': 'High' if data['total_sales'] > 500000 else 'Medium'
            })
    
    return filing_requirements

def analyze_sales_data_excel(file_stream):
    """Analyze sales data from Excel files for tax compliance"""
    try:
        file_stream.seek(0)
        excel_file = pd.ExcelFile(file_stream)
        sheet_names = excel_file.sheet_names
        
        # Combine all sheets for analysis
        combined_df = pd.DataFrame()
        for sheet_name in sheet_names:
            try:
                df = pd.read_excel(excel_file, sheet_name=sheet_name)
                if not df.empty:
                    df['source_sheet'] = sheet_name
                    combined_df = pd.concat([combined_df, df], ignore_index=True)
            except Exception as sheet_error:
                logging.warning(f"Error reading sheet '{sheet_name}': {str(sheet_error)}")
                continue
        
        if combined_df.empty:
            return {
                'type': 'sales_data',
                'error': "No readable data found in Excel file",
                'success': False
            }
        
        # Identify common column patterns
        amount_cols = [col for col in combined_df.columns if any(keyword in col.lower() for keyword in ['amount', 'total', 'price', 'sales', 'revenue'])]
        state_cols = [col for col in combined_df.columns if any(keyword in col.lower() for keyword in ['state', 'region', 'location'])]
        city_cols = [col for col in combined_df.columns if any(keyword in col.lower() for keyword in ['city', 'municipality'])]
        
        # Calculate sales tax analysis with product-based taxability
        product_cols = [col for col in combined_df.columns if any(keyword in col.lower() for keyword in ['product', 'item', 'description', 'type', 'category'])]
        nexus_analysis = analyze_nexus_threshold(combined_df, amount_cols, state_cols, city_cols if city_cols else None)
        tax_obligations = calculate_tax_obligations_by_product(combined_df, amount_cols, state_cols, city_cols if city_cols else None, product_cols if product_cols else None)
        compliance_status = check_compliance_status(nexus_analysis)
        filing_requirements = generate_filing_requirements(nexus_analysis)
        
        return {
            'type': 'sales_data',
            'summary': {
                'total_transactions': len(combined_df),
                'total_revenue': sum([combined_df[col].sum() for col in amount_cols if col in combined_df.columns]),
                'states_with_sales': len(nexus_analysis),
                'nexus_states': len([state for state, data in nexus_analysis.items() if data['has_nexus']]),
                'filing_required': len(filing_requirements),
                'total_sheets': len(sheet_names)
            },
            'nexus_analysis': nexus_analysis,
            'tax_obligations': tax_obligations,
            'compliance_status': compliance_status,
            'filing_requirements': filing_requirements,
            'preview': combined_df.head(10).to_dict('records'),
            'success': True
        }
        
    except Exception as e:
        logging.error(f"Excel sales analysis error: {str(e)}")
        return {
            'type': 'sales_data',
            'error': f"Error analyzing Excel sales data: {str(e)}",
            'success': False
        }

def extract_from_pdf(file_stream):
    """Extract and analyze text from PDF files"""
    try:
        file_stream.seek(0)  # Reset stream position
        doc = fitz.open(stream=file_stream.read(), filetype="pdf")
        
        all_text = ""
        page_count = len(doc)
        
        for page_num in range(page_count):
            page = doc.load_page(page_num)
            text = page.get_text()
            all_text += f"\n--- Page {page_num + 1} ---\n{text}"
        
        doc.close()
        
        # Find lines with dollar amounts
        lines = all_text.split('\n')
        flagged_lines = []
        
        for i, line in enumerate(lines):
            line = line.strip()
            if line and '$' in line:
                # Try to extract dollar amounts
                import re
                dollar_amounts = re.findall(r'\$[\d,]+\.?\d*', line)
                for amount_str in dollar_amounts:
                    try:
                        # Remove $ and commas, convert to float
                        amount = float(amount_str.replace('$', '').replace(',', ''))
                        if amount > 10000:
                            flagged_lines.append({
                                'line_number': i + 1,
                                'content': line,
                                'amount': amount
                            })
                    except ValueError:
                        continue
        
        return {
            'type': 'pdf',
            'summary': {
                'pages': page_count,
                'total_lines': len(lines),
                'flagged_transactions': len(flagged_lines)
            },
            'flagged_data': flagged_lines,
            'preview': all_text[:2000] + ('...' if len(all_text) > 2000 else ''),
            'success': True
        }
        
    except Exception as e:
        logging.error(f"PDF processing error: {str(e)}")
        return {
            'type': 'pdf',
            'error': f"Error processing PDF: {str(e)}",
            'success': False
        }

def extract_from_image(file_stream):
    """Extract and analyze text from images using OCR"""
    try:
        file_stream.seek(0)  # Reset stream position
        image = Image.open(file_stream)
        
        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Perform OCR
        text = pytesseract.image_to_string(image, config='--psm 6')
        
        # Find lines with dollar amounts
        lines = text.split('\n')
        flagged_lines = []
        
        for i, line in enumerate(lines):
            line = line.strip()
            if line and '$' in line:
                # Try to extract dollar amounts
                import re
                dollar_amounts = re.findall(r'\$[\d,]+\.?\d*', line)
                for amount_str in dollar_amounts:
                    try:
                        # Remove $ and commas, convert to float
                        amount = float(amount_str.replace('$', '').replace(',', ''))
                        if amount > 10000:
                            flagged_lines.append({
                                'line_number': i + 1,
                                'content': line,
                                'amount': amount
                            })
                    except ValueError:
                        continue
        
        return {
            'type': 'image',
            'summary': {
                'image_size': f"{image.width}x{image.height}",
                'total_lines': len([l for l in lines if l.strip()]),
                'flagged_transactions': len(flagged_lines)
            },
            'flagged_data': flagged_lines,
            'preview': text[:1500] + ('...' if len(text) > 1500 else ''),
            'success': True
        }
        
    except Exception as e:
        logging.error(f"Image processing error: {str(e)}")
        return {
            'type': 'image',
            'error': f"Error processing image: {str(e)}",
            'success': False
        }

@app.route('/')
def index():
    """Main page with upload form"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and processing"""
    if 'file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('index'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('index'))
    
    # Validate file
    ext, error = validate_file(file.filename)
    if error:
        flash(error, 'error')
        return redirect(url_for('index'))
    
    # Process file based on type
    results = None
    if ext == '.csv':
        results = analyze_sales_data_csv(file.stream)
    elif ext in ['.xlsx', '.xls']:
        results = analyze_sales_data_excel(file.stream)
    elif ext == '.pdf':
        results = extract_from_pdf(file.stream)
    elif ext in ['.png', '.jpg', '.jpeg']:
        results = extract_from_image(file.stream)
    
    if results and results['success']:
        nexus_count = results["summary"].get("nexus_states", 0)
        filing_count = results["summary"].get("filing_required", 0)
        flash(f'Sales tax analysis complete! Found {nexus_count} nexus states and {filing_count} filing requirements.', 'success')
    elif results and not results['success']:
        flash(results['error'], 'error')
        return redirect(url_for('index'))
    
    return render_template('index.html', results=results, filename=secure_filename(file.filename))

@app.errorhandler(413)
def too_large(e):
    flash('File is too large. Maximum size is 10MB.', 'error')
    return redirect(url_for('index'))

@app.errorhandler(500)
def internal_error(e):
    flash('An internal error occurred. Please try again.', 'error')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
