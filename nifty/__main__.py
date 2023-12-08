from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.requests import Request
from starlette.routing import Route
from httpx import AsyncClient
from jsonschema import validate
from json import JSONDecodeError
from datetime import date, datetime
import pandas as pd
import uvicorn, os, stat, json, statistics

# Define stock schema & acceptable price types
_stockSchema = {
    "type": "object",
    "properties": {
        "Date": { "type": "string", "format": "date" },
        "Symbol": { "type": "string"},
        "Close": { "type": "number"},
        "Open": { "type": "number"},
        "High": { "type": "number"},
        "Low": { "type": "number"},
    } 
}
_priceTypes = ["Open", "Close", "High", "Low"]
_fileMode = 0o660|stat.S_IRUSR

# Using logged file data as database
_dataDir = os.getcwd()+"/data"
_filePath = _dataDir+"/nifty50_all.csv"

# In production, the data will come from the frontend (wrapped in request body data)
# For simplicity, I will utilise hard coded dataset for API logic tests
_json_dataset = { "price_data": [
     {
        "Date": "21/08/2031",
        "Symbol": "SBIN",
        "Open": 74.35,
        "High": 75.0,
        "Low": 75.9,
        "Close": 74.15
    }, {
        "Date": "15/07/2038",
        "Symbol": "SBIN",
        "Open": 1257.9,
        "High": 1255.0,
        "Low": 1255.0,
        "Close": 1152.35
    }
]}

# _json_dataset = { "price_data": [
#     {
#         "Date": "15/06/2008",
#         "Symbol": "SBIN",
#         "Open": 1257.9,
#         "High": 1255.0,
#         "Low": 1255.0,
#         "Close": 1152.35
#     }
# ]}

def validate_date_format(_date_str, _format_str):
    try:
        # Try to parse the input date string using the provided format
        datetime.strptime(_date_str, _format_str)
        return True
    except ValueError:
        # If parsing fails, the date format is invalid
        return False

def validateJSON(_dataset):
    # validate the JSON data as expected structure
    try:
        validate(
            instance = _dataset, 
            schema = _stockSchema
            )
    except TypeError as err:
        # In production, log the err
        return False
    return True

async def add_price_data(request: Request) -> JSONResponse:
    """
    func block with logic to allow new data to be validated & added
    """
    # return JSONResponse({"Checked data: ": _json_dataset["price_data"][1]["Date"]})

    try:
        if(os.path.isdir(_dataDir)):
            if(os.path.exists(_filePath)):
                _nifty_df = pd.read_csv(_filePath)
                _nifty_df['Date'] = pd.to_datetime(_nifty_df['Date'], format='%Y-%m-%d')
                # datetime object conversion
                _nifty_df['Date'] = _nifty_df['Date'].apply(lambda x: date.strftime(x, '%d/%m/%Y'))

                for _data_row in _json_dataset["price_data"]:
                    # return JSONResponse({"Checked data: ": _data_row})
                    # Check if the date is in the correct format
                    # try:
                    if(validate_date_format(_data_row["Date"], "%d/%m/%Y") == False):
                        # Invalid, skip
                        continue
                    # except ValueError:
                    #     raise JSONResponse(status_code=400, detail="Invalid date format. Use DD/MM/YYYY")
                    
                    _symbol = _data_row['Symbol'].upper() # make all characters of the input uppercase
                    if(_symbol):
                        if ((_data_row["Symbol"] in _nifty_df["Symbol"].values) & (_data_row["Date"] in (_nifty_df['Date'].drop_duplicates().values))):
                            return JSONResponse(
                                {"error": "Updating or Repetitive Price Data is Forbidden."},
                                status_code=403
                            )
                        else:
                            for pt in _data_row:
                                # of subset is the acceptable OCHL price types?
                                # If no, abandon the data and continue the rest of the loops
                                if (pt not in _priceTypes):
                                    continue
                                    # or return a JSON response and break the loops
                                    # return JSONResponse(
                                    #     {"error": "Data Types other than Open, Close, High and Low are Forbidden ."},
                                    #     status_code=403
                                    # )
                                else:
                                    _related_data = _nifty_df[\
                                        (_nifty_df["Symbol"] == _data_row["Symbol"]) & \
                                        (_nifty_df[pt] == _data_row[pt]\
                                    )]
                                    if(len(_related_data) > 50):
                                        _std_dev = statistics.stdev(_related_data[-50:])
                                        _new_price = _data_row[pt]
                                        if not (_new_price - _std_dev <= statistics.mean(_related_data[-50:]) <= _new_price + _std_dev):
                                            return JSONResponse(
                                                {"error": "Price not within 1 standard deviation of prior 50 values"},
                                                status_code=400,
                                            )
                                        # the specification didn't say what happen if it's not, I will mark it as None
                                        else:
                                            _data_row[pt] = None

                            if(_data_row):        
                                # Append data if any
                                _nifty_df = pd.concat([_nifty_df, pd.DataFrame([_data_row])]).reset_index(drop=True)   
                    else:
                        # If request body has no values, return an error code
                        return JSONResponse(
                            {"error": "Bad Request - Symbol Not Found."}, 
                            status_code=400
                        )
                    
                # after all data have been updated above within the _nifty_df
                # convert all datetime to its original CSV format
                _nifty_df["Date"] = pd.to_datetime(_nifty_df["Date"], format="%d/%m/%Y", errors = "coerce")
                _nifty_df['Date'] = _nifty_df['Date'].dt.strftime('%Y-%m-%d')
                # persist it back to the CSV file, so the new price data will be accessible via GET from prev endpoint
                _nifty_df.to_csv(_filePath, mode='w', index=False, header=["Date","Symbol","Close","Open","High","Low"]) 
                
                
                return JSONResponse(
                    "Price data is added Successfully", 
                    status_code=200
                )
            else:
                # If cannot find the destinated data file, create one for further data appending
                os.mknod(_filePath, _fileMode)
                return JSONResponse(
                    {"error": "Not Found - Requested File Not Found."},
                    status_code=404
                )
        else:
            # If data directory doesn't exist, create one
            os.mkdir(_dataDir)
            return JSONResponse(
                {"error": "Not Found - Directory Not Found."}, 
                status_code=404
            ) 
        
    except JSONDecodeError:
        return JSONResponse(
            {"error": "Internal Server Errors"}, 
            status_code=500
        )

async def price_data(request: Request) -> JSONResponse:
    """
    Return price data for the requested symbol w/ or w/o extra query year params
    """
    try:
        _symbol = request.path_params['symbol'].upper() # make the input all uppercase
        _dataDir = os.getcwd()+"/data"
        _filePath = _dataDir+"/nifty50_all.csv"
        # determine whether an extra query param is enrolled
        if(request.query_params and (request.query_params['year']).isdigit() == False): # intecept any illegal/malicious inputs, e.g. '201O' rather than '2010'
            return JSONResponse(
                    {"error": "Invalid Year Is Given"},
                    status_code=400
                )
        elif(request.query_params and int(request.query_params['year'])): # check data existence
            _q_param = int(request.query_params['year']) # data type casting
        else:
            _q_param = None
            
        if(_symbol):
            if(os.path.isdir(_dataDir)):
                if(os.path.exists(_filePath)):
                    _nifty_df = pd.read_csv(_filePath)
                    
                    if(isinstance(_q_param, int) and _q_param): # make sure is instance of integer & defined
                        # 2) Allow calling app to filter the data by year using an optional query parameter
                        _nifty_df['Date'] = pd.to_datetime(_nifty_df['Date'], format='%Y-%m-%d')
                        _filtered_df = _nifty_df[_nifty_df['Date'].dt.year == int(_q_param)]
                        # convert datetime back to datetime strings
                        _filtered_df['Date'] = _filtered_df['Date'].apply(lambda x: date.strftime(x, '%Y-%m-%d'))
                        # break lines for better readability
                        _res = _filtered_df[_filtered_df['Symbol'] == _symbol] \
                                        .sort_values(by="Date", ascending=False) \
                                            .to_json(orient='records')
                        if(_res):
                            return JSONResponse({'JSON Response is:': json.loads(_res) })
                        else:
                            return JSONResponse({
                                "No Data For The Specified Year: ":
                                "[]"
                            }, status_code = 400)
                        
                    elif(isinstance(_symbol, str) and _q_param is None):
                        # 1) Return open, high, low & close prices for the requested symbol as json records
                        _res = _nifty_df[_nifty_df['Symbol'] == _symbol] \
                                .sort_values(by="Date", ascending=False) \
                                    .to_json(orient='records')
                        if(_res):
                            return JSONResponse({'JSON Response is:': json.loads(_res) })
                        else:
                            return JSONResponse(
                                {"error": "Bad Request - Request Data Not Found."},
                                status_code=400
                            )
                    else:
                        return JSONResponse(
                            {"error": "Bad Request - Year Query Param Is Not Integer."},
                            status_code=400
                        )
                    
                else:
                    # If cannot find the destinated data file, create one for further data appending
                    os.mknod(_filePath, _fileMode)
                    return JSONResponse(
                        {"error": "Not Found - Requested File Not Found."},
                         status_code=404
                    )
            else:
                # If data directory doesn't exist, create one
                os.mkdir(_dataDir)
                return JSONResponse(
                    {"error": "Not Found - Directory Not Found."}, 
                    status_code=404
                ) 
        else:
            # If request body has no values, throw an error code
            return JSONResponse(
                {"error": "Bad Request - Symbol Not Found."}, 
                status_code=400
            )
              
    except JSONDecodeError:
        return JSONResponse(
            {"error": "Internal Server Errors"}, 
            status_code=500
        )


# URL routes
app = Starlette(debug=True, routes=[
    Route('/nifty/stocks/{symbol}', price_data, methods=["GET"]),
    # for adding data, usually should just be "POST" method, I added "GET" to use hardcoded data with browser for quick tests
    Route('/nifty/stocks/add/', add_price_data, methods=["GET", "POST"])
])


def main() -> None:
    """
    start the server
    """
    uvicorn.run(app, host='127.0.0.1', port=8888)
    
# Entry point
main()
