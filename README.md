# Arbscreener Flask Application

## Overview

This project is a Flask-based web application that integrates with the Dexscreener API to display cryptocurrency token pair details. The application generates dynamic HTML content to visualize token liquidity, prices, and volumes, providing a user-friendly interface for exploring token data.

## Features

- **Dynamic Token Pair Cards:** Display token pair details including liquidity, price, and volume in an organized card format.
- **Interactive Summary Display:** Click on a token pair card to display detailed information in a fixed summary div.
- **Charts Visualization:** Generate pie and tree charts for liquidity and volume data using Matplotlib and Squarify.
- **Responsive Design:** The layout adapts to different screen sizes, ensuring a consistent user experience across devices.

## Project Structure


<!-- project-root/
├── main.py              # Main Flask application file
├── templates/           # HTML templates for the application
│   ├── base.html        # Base template for consistent layout
│   ├── index.html       # Main page displaying token pair cards
│   ├── charts.html      # Page displaying liquidity and volume charts
│   ├── summary.html     # Page displaying a summary of token pair data
│   ├── token_summary.html # Page displaying detailed token pair statistics
│   └── ...
├── static/              # Directory for static files (e.g., CSS, JavaScript)
│   ├── style.css        # Custom styles for the application
│   └── ...
├── README.md            # Project documentation
└── requirements.txt     # Python dependencies -->

### Documentation files
    project-root/
    ├── main.py              # Main Flask application file
    ├── templates/           # HTML templates for the application
    │   ├── base.html        # Base template for consistent layout
    │   ├── index.html       # Main page displaying token pair cards
    │   ├── charts.html      # Page displaying liquidity and volume charts
    │   ├── summary.html     # Page displaying a summary of token pair data
    │   ├── token_summary.html # Page displaying detailed token pair statistics
    │   └── ...
    ├── static/              # Directory for static files (e.g., CSS, JavaScript)
    │   ├── style.css        # Custom styles for the application
    │   └── ...
    ├── README.md            # Project documentation
    └── requirements.txt     # Python dependencies


## Installation

### Prerequisites

- Python 3.x
- Pip (Python package installer)

### Setup

1. **Clone the repository:**

    ```bash
    git clone https://github.com/your-username/dexscreener-flask.git
    cd dexscreener-flask
    ```

2. **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

3. **Run the application:**

    ```bash
    python app.py
    ```

4. **Open your browser and navigate to:**

    ```
    http://127.0.0.1:5000/
    ```

## Usage

- **Homepage:** Displays token pair cards with basic information like chain ID, liquidity, price, and volume.
- **Click a Card:** Opens a detailed summary with more information and an interactive chart for the selected token pair.
- **Charts Page:** Provides visual insights into the liquidity and volume data of token pairs.

## Customization

### API Integration

The application integrates with the Dexscreener API using the `dexscreener` Python package. You can customize the token pairs displayed by modifying the `searchTicker` parameter in the `index()` function in `app.py`.

### Styling

The application uses custom CSS for styling. You can modify `style.css` located in the `static` directory to change the look and feel of the application.

### Chart Visualization

The charts are generated using Matplotlib and Squarify. You can modify the functions `tree_chart_liquidity`, `pie_chart_liquidity`, `tree_chart_volume`, and `pie_chart_volume` in `app.py` to customize the chart appearance.

## Dependencies

- Flask
- Matplotlib
- Numpy
- Pandas
- Squarify
- Dexscreener
- Plotly

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

![image](https://github.com/user-attachments/assets/ce363fa7-dae2-451b-909d-5d8fd812006d)

![image](https://github.com/user-attachments/assets/997ca61f-8e06-4615-97aa-42a3a86addcc)

![image](https://github.com/user-attachments/assets/4f8102e3-3394-4786-bb9c-afdca85de3a0)



