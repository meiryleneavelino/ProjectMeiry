import pandas as pd
import numpy as np
import seaborn as sns
from sklearn.model_selection import train_test_split
from sklearn.ensemble import GradientBoostingRegressor
import matplotlib.pyplot as plt
import torch


step=1 # step size for iterations. The lower the slower.
fig_width = 7.5 # width of figures
fig_height = 5 # height of figures
k=25 # number of largest feature importances


#import os
#os.path.join('input/2015-residential-energy-consumption-survey/')


houses_df=pd.read_csv(r"C:\Users\alkou\Documents\GitHub\Scattered-Directive\house_energy_consumption\recs2015_public_v4.csv")
houses_df.head()


# check if colunms contain null-values. If yes, replace with 0.
if houses_df[['BTUELSPH','BTUFOSPH','BTUNGSPH','BTULPSPH', 'BTUELCOL','BTUELWTH','BTUFOWTH','BTUNGWTH',
                                    'BTULPWTH','BTUELAHUCOL','BTUNGPLHEAT','BTUELHTBHEAT','BTUNGHTBHEAT','BTUELHTBPMP']].isnull().values.any()==True:
    print('Some columns contain Null values.')
    houses_df[['BTUELSPH','BTUFOSPH','BTUNGSPH','BTULPSPH', 'BTUELCOL','BTUELWTH','BTUFOWTH','BTUNGWTH',
                                    'BTULPWTH','BTUELAHUCOL','BTUNGPLHEAT','BTUELHTBHEAT','BTUNGHTBHEAT','BTUELHTBPMP']].fillna(0)
else: print('No columns contain Null values.')
print('Number of cells before deletion of energy usage: ',houses_df.shape)

# calculate total relevant BTU consumption and delete energy consumption cells afterwards.
houses_df['REL_TOTALBTU']=houses_df[['BTUELSPH','BTUFOSPH','BTUNGSPH','BTULPSPH', 'BTUELCOL','BTUELWTH','BTUFOWTH','BTUNGWTH',
                                    'BTULPWTH','BTUELAHUCOL','BTUNGPLHEAT','BTUELHTBHEAT','BTUNGHTBHEAT','BTUELHTBPMP']].sum(axis=1)
houses_df=houses_df.drop(columns=['DOEID','NWEIGHT','BRRWT1','BRRWT2','BRRWT3','BRRWT4','BRRWT5','BRRWT6','BRRWT7','BRRWT8','BRRWT9','BRRWT10',
                        'BRRWT11','BRRWT12','BRRWT13','BRRWT14','BRRWT15','BRRWT16','BRRWT17','BRRWT18','BRRWT19','BRRWT20','BRRWT21',
                        'BRRWT22','BRRWT23','BRRWT24','BRRWT25','BRRWT26','BRRWT27','BRRWT28','BRRWT29','BRRWT30','BRRWT31','BRRWT32',
                        'BRRWT33','BRRWT34','BRRWT35','BRRWT36','BRRWT37','BRRWT38','BRRWT39','BRRWT40','BRRWT41','BRRWT42','BRRWT43',
                        'BRRWT44','BRRWT45','BRRWT46','BRRWT47','BRRWT48','BRRWT49','BRRWT50','BRRWT51','BRRWT52','BRRWT53','BRRWT54',
                        'BRRWT55','BRRWT56','BRRWT57','BRRWT58','BRRWT59','BRRWT60','BRRWT61','BRRWT62','BRRWT63','BRRWT64','BRRWT65',
                        'BRRWT66','BRRWT67','BRRWT68','BRRWT69','BRRWT70','BRRWT71','BRRWT72','BRRWT73','BRRWT74','BRRWT75','BRRWT76',
                        'BRRWT77','BRRWT78','BRRWT79','BRRWT80','BRRWT81','BRRWT82','BRRWT83','BRRWT84','BRRWT85','BRRWT86','BRRWT87',
                        'BRRWT88','BRRWT89','BRRWT90','BRRWT91','BRRWT92','BRRWT93','BRRWT94','BRRWT95','BRRWT96',
                        'KWH','KWHSPH','KWHCOL','KWHWTH','KWHRFG','KWHRFG1','KWHRFG2','KWHFRZ','KWHCOK','KWHMICRO','KWHCW','KWHCDR',
                        'KWHDWH','KWHLGT','KWHTVREL','KWHTV1','KWHTV2','KWHAHUHEAT','KWHAHUCOL','KWHEVAPCOL','KWHCFAN','KWHDHUM',
                        'KWHHUM','KWHPLPMP','KWHHTBPMP','KWHHTBHEAT','KWHNEC','BTUEL','BTUELSPH','BTUELCOL','BTUELWTH','BTUELRFG',
                        'BTUELRFG1','BTUELRFG2','BTUELFRZ','BTUELCOK','BTUELMICRO','BTUELCW','BTUELCDR','BTUELDWH','BTUELLGT',
                        'BTUELTVREL','BTUELTV1','BTUELTV2','BTUELAHUHEAT','BTUELAHUCOL','BTUELEVAPCOL','BTUELCFAN','BTUELDHUM',
                        'BTUELHUM','BTUELPLPMP','BTUELHTBPMP','BTUELHTBHEAT','BTUELNEC','DOLLAREL','DOLELSPH','DOLELCOL','DOLELWTH',
                        'DOLELRFG','DOLELRFG1','DOLELRFG2','DOLELFRZ','DOLELCOK','DOLELMICRO','DOLELCW','DOLELCDR','DOLELDWH',
                        'DOLELLGT','DOLELTVREL','DOLELTV1','DOLELTV2','DOLELAHUHEAT','DOLELAHUCOL','DOLELEVAPCOL','DOLELCFAN',
                        'DOLELDHUM','DOLELHUM','DOLELPLPMP','DOLELHTBPMP','DOLELHTBHEAT','DOLELNEC','CUFEETNG','CUFEETNGSPH',
                        'CUFEETNGWTH','CUFEETNGCOK','CUFEETNGCDR','CUFEETNGPLHEAT','CUFEETNGHTBHEAT','CUFEETNGNEC','BTUNG','BTUNGSPH',
                        'BTUNGWTH','BTUNGCOK','BTUNGCDR','BTUNGPLHEAT','BTUNGHTBHEAT','BTUNGNEC','DOLLARNG','DOLNGSPH','DOLNGWTH',
                        'DOLNGCOK','DOLNGCDR','DOLNGPLHEAT','DOLNGHTBHEAT','DOLNGNEC','GALLONLP','GALLONLPSPH','GALLONLPWTH',
                        'GALLONLPCOK','GALLONLPCDR','GALLONLPNEC','BTULP','BTULPSPH','BTULPWTH','BTULPCOK','BTULPCDR','BTULPNEC',
                        'DOLLARLP','DOLLPSPH','DOLLPWTH','DOLLPCOK','DOLLPCDR','DOLLPNEC','GALLONFO','GALLONFOSPH','GALLONFOWTH',
                        'GALLONFONEC','BTUFO','BTUFOSPH','BTUFOWTH','BTUFONEC','DOLLARFO','DOLFOSPH','DOLFOWTH','DOLFONEC','TOTALBTU',
                        'TOTALDOL','TOTALBTUSPH','TOTALDOLSPH','TOTALBTUWTH','TOTALDOLWTH','TOTALBTUCOK','TOTALDOLCOK','TOTALBTUCDR',
                        'TOTALDOLCDR','TOTALBTUPL','TOTALDOLPL','TOTALBTUHTB','TOTALDOLHTB','TOTALBTUNEC','TOTALDOLNEC','WOODAMT',
                        'WOODBTU','PELLETAMT','PELLETBTU','ELXBTU','PERIODEL','NGXBTU','PERIODNG','FOXBTU','PERIODFO','LPXBTU',
                        'PERIODLP'])
print('Number of cells after deletion of unnecessary energy usage columns: ',houses_df.shape)

# deleting Z-columns
houses_df=houses_df.drop(columns=['ZADQINSUL', 'ZAGECDRYER', 'ZAGECENAC', 'ZAGECWASH', 'ZAGEDW', 'ZAGEFRZR', 'ZAGERFRI1', 'ZAGERFRI2','ZAIRCOND', 'ZALTFUELPEV', 'ZAMTMICRO', 'ZAPPOTHER', 'ZATHOME', 'ZATTCCOOL', 'ZATTCHEAT', 'ZATTIC', 
                                  'ZATTICFIN', 'ZBACKUP', 'ZBASECOOL', 'ZBASEFIN', 'ZBASEHEAT', 'ZBEDROOMS', 'ZBLENDER', 'ZCABLESAT', 
                                  'ZCELLAR', 'ZCELLPHONE', 'ZCENACHP', 'ZCOFFEE', 'ZCOLDMA', 'ZCOMBODVR', 'ZCOOKTUSE', 'ZCOOLTYPE', 
                                  'ZCROCKPOT', 'ZCWASHER', 'ZDESKTOP', 'ZDISHWASH', 'ZDNTHEAT', 'ZDOOR1SUM', 'ZDRAFTY', 'ZDRYER', 
                                  'ZDRYRFUEL', 'ZDRYRUSE', 'ZDUALCOOKTFUEL', 'ZDUALOVENFUEL', 'ZDVD', 'ZDWASHUSE', 'ZDWCYCLE', 
                                  'ZEDUCATION', 'ZELPAY', 'ZELPERIPH', 'ZEMPLOYHH', 'ZENERGYASST', 'ZENERGYASST11', 'ZENERGYASST12', 
                                  'ZENERGYASST13', 'ZENERGYASST14', 'ZENERGYASST15', 'ZENERGYASSTOTH', 'ZEQUIPAGE', 'ZEQUIPAUX', 
                                  'ZEQUIPAUXTYPE', 'ZEQUIPM', 'ZEQUIPMUSE', 'ZFOODPROC', 'ZFOPAY', 'ZFUELAUX', 'ZFUELH2O', 
                                  'ZFUELH2O2', 'ZFUELHEAT', 'ZFUELPOOL', 'ZFUELTUB', 'ZGARGCOOL', 'ZGARGHEAT', 'ZH2OHEATAPT', 
                                  'ZHEATHOME', 'ZHHAGE', 'ZHHSEX', 'ZHIGHCEIL', 'ZHOTMA', 'ZHOUSEHOLDER_RACE', 'ZICE', 'ZINTERNET', 
                                  'ZINTSTREAM', 'ZINWIRELESS', 'ZKOWNRENT', 'ZLGTIN4', 'ZLGTINCAN', 'ZLGTINCFL', 'ZLGTINCNTL', 
                                  'ZLGTINLED', 'ZLGTINNUM', 'ZLGTOUTCNTL', 'ZLGTOUTNUM', 'ZLOCRFRI2', 'ZLPGPAY', 'ZMICRO', 'ZMOISTURE', 
                                  'ZMONEYPY', 'ZMONPOOL', 'ZMONTUB', 'ZMORETHAN1H2O', 'ZNCOMBATH', 'ZNGPAY', 'ZNHAFBATH', 'ZNHSLDMEM', 
                                  'ZNOACBROKE', 'ZNOACDAYS', 'ZNOACEL', 'ZNOACHELP', 'ZNOHEATBROKE', 'ZNOHEATBULK', 'ZNOHEATDAYS', 
                                  'ZNOHEATEL', 'ZNOHEATHELP', 'ZNOHEATNG', 'ZNOTMOIST', 'ZNUMADULT', 'ZNUMATTICFAN', 'ZNUMBERAC', 
                                  'ZNUMCFAN', 'ZNUMCHILD', 'ZNUMFLOORFAN', 'ZNUMFREEZ', 'ZNUMFRIG', 'ZNUMLAPTOP', 'ZNUMMEAL', 
                                  'ZNUMSMPHONE', 'ZNUMTABLET', 'ZNUMWHOLEFAN', 'ZOCCUPYYRANGE', 'ZOTHROOMS', 'ZOUTGRILL', 
                                  'ZOUTGRILLFUEL', 'ZOUTLET', 'ZOVEN', 'ZOVENFUEL', 'ZOVENUSE', 'ZPAYHELP', 'ZPLAYSTA', 'ZPOOL', 
                                  'ZPRKGPLC1', 'ZPROTHERM', 'ZPROTHERMAC', 'ZRECBATH', 'ZRICECOOK', 'ZRNSETEMP', 'ZROOFTYPE', 'ZSCALEB', 
                                  'ZSCALEE', 'ZSCALEG', 'ZSDESCENT', 'ZSEPCOOKTUSE', 'ZSEPDVR', 'ZSEPOVENUSE', 'ZSIZEOFGARAGE', 
                                  'ZSIZFREEZ', 'ZSIZRFRI1', 'ZSIZRFRI2', 'ZSTORIES', 'ZSTOVE', 'ZSTOVEFUEL', 'ZSTOVEN', 'ZSTOVENFUEL', 
                                  'ZSTUDIO', 'ZSWAMPCOL', 'ZSWIMPOOL', 'ZTEMPGONE', 'ZTEMPGONEAC', 'ZTEMPHOME', 'ZTEMPHOMEAC', 
                                  'ZTEMPNITE', 'ZTEMPNITEAC', 'ZTHERMAIN', 'ZTHERMAINAC', 'ZTOAST', 'ZTOASTOVN', 'ZTOPFRONT', 
                                  'ZTOTROOMS', 'ZTOTSQFT_EN', 'ZTVAUDIOSYS', 'ZTVCOLOR', 'ZTVONWD1', 'ZTVONWD2', 'ZTVONWE1', 'ZTVONWE2', 
                                  'ZTVSIZE1', 'ZTVSIZE2', 'ZTVTYPE1', 'ZTVTYPE2', 'ZTYPEGLASS', 'ZTYPEHUQ', 'ZTYPERFR1', 'ZTYPERFR2', 
                                  'ZUGASHERE', 'ZUPRTFRZR', 'ZUSECENAC', 'ZUSEMOISTURE', 'ZUSENOTMOIST', 'ZUSEWWAC', 'ZVCR', 'ZWALLTYPE', 
                                  'ZWASHLOAD', 'ZWASHTEMP', 'ZWDPELLET', 'ZWHEATAGE', 'ZWHEATSIZ', 'ZWINDOWS', 'ZWINFRAME', 'ZWOODLOGS', 
                                  'ZWWACAGE', 'ZYEARMADERANGE'])
print('Number of cells after deletion of Z-columns: ',houses_df.shape)



# deleting columns for appliances and electronic household devices
houses_df=houses_df.drop(columns=['OUTLET','ALTFUELPEV','BACKUP','SOLAR','NUMFRIG','SIZRFRI1','TYPERFR1','AGERFRI1','ICE','SIZRFRI2',
                                  'TYPERFR2','AGERFRI2','LOCRFRI2','NUMFREEZ','UPRTFRZR','SIZFREEZ','AGEFRZR','STOVEN','STOVENFUEL',
                                  'DUALCOOKTFUEL','DUALOVENFUEL','COOKTUSE','OVENUSE','STOVE','STOVEFUEL','SEPCOOKTUSE','OVEN',
                                  'OVENFUEL','SEPOVENUSE','MICRO','AMTMICRO','OUTGRILL','OUTGRILLFUEL','NUMMEAL','TOAST','TOASTOVN',
                                  'COFFEE','CROCKPOT','FOODPROC','RICECOOK','BLENDER','APPOTHER','DISHWASH','DWASHUSE','DWCYCLE',
                                  'AGEDW','CWASHER','TOPFRONT','WASHLOAD','WASHTEMP','RNSETEMP','AGECWASH','DRYER','DRYRFUEL',
                                  'DRYRUSE','AGECDRYER','TVCOLOR','TVSIZE1','TVTYPE1','TVONWD1','TVONWE1','TVSIZE2','TVTYPE2',
                                  'TVONWD2','TVONWE2','CABLESAT','COMBODVR','SEPDVR','PLAYSTA','DVD','VCR','INTSTREAM','TVAUDIOSYS',
                                  'DESKTOP','NUMLAPTOP','NUMTABLET','ELPERIPH','NUMSMPHONE','CELLPHONE','INTERNET','INWIRELESS'])

# Mapping certain features.
replacements = {
    'REGIONC' : {1: 'Northeast', 2: 'Midwest', 3:'South', 4 : 'West'},
    'DIVISION' : {1: 'New England', 2 : 'Middle Atlantic' , 3 : 'East North Central', 4 : 'West North Central', 5 :'South Atlantic' , 
                  6: 'East South Central', 7: 'West South Central', 8: 'Mountain North', 9: 'Mountain South' , 10 : ' Pacific '},
    'TYPEHUQ': {1: 'Mobile home' , 2: 'Single-family detached house', 3 : 'single- family attached house', 
                4 : 'Apartment in a building with 2 to 4 units', 5: 'Apartment in a building with 5 or more units'},
    'CELLAR' : {1 : 'Yes', 0 : 'No', -2 : 'Not Applicable'},
    'BASEFIN': {1: 'Yes', 0 : 'No', -2: 'Not Applicable'},
    'ATTIC': {1 : 'Yes', 0: 'No', -2 : 'Not Applicable'},
    'ATTICFIN' : {1 :'Yes', 0 : 'No', -2: 'Not Applicable' },
    'STORIES' : {10 : 'One story', 20 : 'Two stories', 31 : 'Three stories', 32 : 'Four or more stories', 40: 'Split-level', 
                 -2: 'Not Applicable'},
    'PRKGPLC1' : {1 : 'Yes', 0: 'No', -2 : 'Not Applicable'},
    'SIZEOFGARAGE' : {1 : 'One-car garage', 2 : 'Two-car garage', 3: 'Three-or-more-car garage' , -2 : 'Not Applicable'},
    'KOWNRENT': {1 : 'Owned or being bought by someone in your household', 2 : 'Rented', 3 : 'Occupied without payment of rent'},
    'YEARMADERANGE': {1 : 'Before 1950', 2 : '1950 to 1959', 3 : '1960 to 1969', 4 : '1970 to 1979', 5 :'1980 to 1989', 
                      6 : '1990 to 1999', 7 : '2000 to 2009', 8: '2010 to 2015'},
    'OCCUPYYRANGE' : {1 : 'Before 1950', 2 : '1950 to 1959', 3 : '1960 to 1969', 4 : '1970 to 1979', 5 :'1980 to 1989', 
                      6 : '1990 to 1999', 7 : '2000 to 2009', 8: '2010 to 2015'},
    'STUDIO': {1 :'Yes', 0 : 'No', -2 : 'Not Applicable'},
    'WALLTYPE': {1 : 'Brick', 2: 'Wood', 3: 'Siding', 4 : 'Stucco', 5: 'Shingle (composition)', 6:'Stone', 
                 7 : 'Concrete or concrete block', 9: '0ther'},
    'ROOFTYPE': {1 : 'Ceramic or clay tiles', 2: 'Wood shingles/shakes', 3: 'Metal', 4: 'Slate or synthetic shake', 
                 5 : 'Shingles (composition or asphalt)) ', 7: 'Concrete tiles', 9: 'Other', -2 : 'Not Applicable'},
    'HIGHCEIL' : {1: 'Yes', 0 :'No', -2 : 'Not Applicable'},
    'WINDOWS': {10 : '1 to 2', 20: '3 to 5', 30 : '6 to 9', 41 : '10 to 15', 42 : '16 to 19, 50:20 to 29', 60:' 30 or more'},
    'TYPEGLASS': {1 : 'Single-pane glass', 2: 'Double-pane glass', 3 : 'Triple-pane glass'},
    'WINFRAME': {1 : 'Wood', 2 : 'Metal (aluminum)', 3 : 'Vinyl', 4 : 'Composite', 5 : 'Fiberglass'},
    'ADQINSUL': {1: 'Well insulated', 2 : 'Adequately insulated', 3 :'Poorly insulated', 4 : 'Not insulated'},
    'DRAFTY': {1: 'All the time', 2: 'Most of the time',3 : 'Some of the time', 4: 'Never'},
    'SWIMPOOL' : {1 : 'Yes', 0 : 'No', -2 : 'Not Applicable'},
    'POOL' : {1 : 'Yes', 0 : 'No' , -2 : 'Not Applicable'},
    'FUELPOOL': {1 : 'Natural gas from underground pipes', 2: 'Propane (bottled gas)', 3 :'Fuel oil/kerosene', 5:'Electricity', 
                 8:'Solar', 21 :'Some other fuel', -2 : 'Not Applicable'},
    'EQUIPM': {2 : 'Steam/hot water system with radiators or pipes', 3 :'Central furnace', 4 : 'Heat pump', 
               5 : 'Built-in electric units installed in walls, ceilings, baseboards, or floors', 
               6 : 'Built-in floor/wall pipeless furnace', 7 : 'Built-in room heater burning gas, oil, or kerosene', 
               8 : 'Wood-burning stove (cordwood or pellets)', 9 : 'Fireplace', 10 : 'Portable electric heaters', 
               21 : 'Some other equipment',  -2 : 'Not Applicable'},
    'FUELHEAT': {1 : 'Natural gas from underground pipes', 2 : 'Propane (bottled gas)', 3 :'Fuel oil/kerosene', 5: 'Electricity', 
                 7 : 'Wood (cordwood or pellets)', 21 : 'Some other fuel', -2: 'Not Applicable'},
    'EQUIPAGE': {1 : 'Less than 2 years old', 2 : '2 to 4 years old', 3 :'5 to 9 years old', 41 : '10 to 14 years old',
                 42 : '15 to 19 years old', 5 : '20 years old', -2 : 'Not Applicable'},
    'BASEHEAT': {1 : 'Yes', 0 : 'No', -2: 'Not Applicable'},
    'FUELH2O' : {1 : 'Natural gas from underground pipes', 2 : 'Propane (bottled gas)', 3 :'Fuel oil/kerosene', 
                 5 : 'Electricity', 7: 'Wood (cordwood or pellets) ', 8 : 'Solar', 21: 'Some other fuel'},
    'BASECOOL': {1 : 'Yes', 0 : 'No', -2 : 'Not Applicable'}
    }
             # Remap the values of the dataframe
for i in replacements:
    dict=replacements [i]
    houses_df[i] .replace (dict, inplace=True)
houses_df.head()


# Getting numerical and categorical columns as preparation for one hot encoding
cols=houses_df.columns
num_cols=list(houses_df._get_numeric_data().columns)
cat_cols=list(set(cols)-set(num_cols))
print(f'num_cols:\n{num_cols}\n\ncat_cols:{cat_cols}')


# print(json.dumps(list(cols), indent=2))

column_categories = json.load(open(r'C:\Users\alkou\Documents\GitHub\Scattered-Directive\house_energy_consumption\column_categories.json', encoding='utf-8'))

categories = list(column_categories.keys())
for category in categories: 
    print(f'{category}: {column_categories[category][:5]}')

# print(list(column_categories.keys()))

# TODO: 
# separate columns in 3 categories semantically 
# Maybe the following: 
# 1. Features related to the building structure
# 2. Features related to the household demographics
# 3. Features related to energy consumption

# one hot encoding of categorical columns
houses_df=pd.get_dummies(data=houses_df, columns=cat_cols)
houses_df.head()


# Remove n/a columns
houses_df=houses_df.drop(columns=['BASECOOL_Not Applicable', 'BASEHEAT_Not Applicable', 'BASEFIN_Not Applicable', 
                                  'ROOFTYPE_Not Applicable', 'FUELPOOL_Not Applicable', 'SWIMPOOL_Not Applicable', 
                                  'STUDIO_Not Applicable', 'ATTICFIN_Not Applicable', 'POOL_Not Applicable', 
                                  'PRKGPLC1_Not Applicable', 'HIGHCEIL_Not Applicable', 'SIZEOFGARAGE_Not Applicable', 
                                  'ATTIC_Not Applicable', 'CELLAR_Not Applicable', 'STORIES_Not Applicable', 
                                  'EQUIPM_Not Applicable', 'EQUIPAGE_Not Applicable'])

# Remove 'no' columns
houses_df=houses_df.drop(columns=['BASEHEAT_No', 'PRKGPLC1_No', 'BASECOOL_No', 'CELLAR_No', 'ATTICFIN_No', 'HIGHCEIL_No', 
                                  'ATTIC_No', 'POOL_No', 'SWIMPOOL_No', 'BASEFIN_No', 'STUDIO_No'])

# Removing behaviour based features, which are not known a priori, and other features which are hard to obtain.
houses_df=houses_df.drop(columns=['HDD50', 'HDD65', 'CDD65', 'CDD30YR', 'DBT99', 'HDD30YR', 'GNDHDD65', 'GWT', 'SWAMPCOL', 'WSF', 'OA_LAT', 'TEMPHOMEAC'])


# TODO: 
#  normalize data 
#  make a NN model 

target=houses_df['REL_TOTALBTU']
data=houses_df.drop(columns=['REL_TOTALBTU'])

data.describe()

from sklearn.preprocessing import StandardScaler

data_encoded = pd.get_dummies(data, columns=cat_cols, drop_first=True)
print("\n--- DataFrame After One-Hot Encoding ---")
print(data_encoded.head())

scaler = StandardScaler()
scaled_data = scaler.fit_transform(data_encoded)

# Save data 
scaled_data_df = pd.DataFrame(scaled_data, columns=data_encoded.columns)
scaled_data_df.to_csv(r'C:\Users\alkou\Documents\GitHub\Scattered-Directive\house_energy_consumption\preprocessed_data\scaled_data.csv', index=False)

target.to_csv(r'C:\Users\alkou\Documents\GitHub\Scattered-Directive\house_energy_consumption\preprocessed_data\target.csv', index=False)


X_train, X_test, y_train, y_test = train_test_split(scaled_data, target, test_size=0.25)

X_train_tensor = torch.tensor(X_train.toarray() if hasattr(X_train, "toarray") else X_train, dtype=torch.float32)
X_test_tensor = torch.tensor(X_test.toarray() if hasattr(X_test, "toarray") else X_test, dtype=torch.float32)

# Convert target Series to tensors
y_train_tensor = torch.tensor(y_train.values, dtype=torch.float32).unsqueeze(1)
y_test_tensor = torch.tensor(y_test.values, dtype=torch.float32).unsqueeze(1)


import torch.nn as nn
import torch.optim as optim

# A simple model with one fully connected (Linear) layer.
class SimpleRegressionNN(nn.Module):
    def __init__(self, input_size):
        super(SimpleRegressionNN, self).__init__()
        # Single linear layer that maps input_size features to 1 output value
        self.fc1 = nn.Linear(input_size, 1)

    def forward(self, x):
        # Pass the input through the linear layer
        return self.fc1(x)

# Hyperparameters
learning_rate = 0.1
epochs = 100

# Determine input size from your data
input_size = X_train_tensor.shape[1]

# Instantiate the model
model = SimpleRegressionNN(input_size)

# Loss function for regression: Mean Squared Error (MSE)
criterion = nn.MSELoss()

# Optimizer: Adam is a good default choice
optimizer = optim.Adam(model.parameters(), lr=learning_rate)

print("--- Starting Training ---")
# --- 4. Training Loop ---
for epoch in range(epochs):
    # Set the model to training mode
    model.train()

    # 1. Forward pass: compute predicted y by passing x to the model
    y_pred = model(X_train_tensor)

    # 2. Compute loss
    loss = criterion(y_pred, y_train_tensor)

    # 3. Zero gradients, perform a backward pass, and update the weights.
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()

    # Print loss every 10 epochs to monitor progress
    if (epoch + 1) % 10 == 0:
        print(f'Epoch [{epoch+1}/{epochs}], Loss: {loss.item():.4f}')

print("--- Training Finished ---")


model.eval()

with torch.no_grad():
    test_predictions = model(X_test_tensor)
    print("\n--- Sample Predictions on Test Data ---")
    # Print the first 5 predictions
    print(test_predictions[:5])


























# Performing train test split
target=houses_df['REL_TOTALBTU']
data=houses_df.drop(columns=['REL_TOTALBTU'])
X_train, X_test, y_train, y_test = train_test_split(data, target, test_size=0.25)


# Building model
reg=GradientBoostingRegressor(random_state=123, min_samples_leaf=1, n_estimators=2000, learning_rate=0.01, subsample=0.2)
reg.fit(X_train, y_train)
predictions_df=pd.DataFrame(index=X_test.index)
predictions_df['est_consumption']=reg.predict(X_test)
reg.score(X_test, y_test)


# Visualize model predictions vs. actuals
plt.scatter(y_test, predictions_df['est_consumption'])
plt.xlabel('actual consumption (BTU)')
plt.ylabel('estimated consumption')
plt.xlim([0, 200000])
plt.ylim([0, 200000])
plt.plot([0,200000],[0,200000],marker='o', alpha=0.5)
plt.rcParams['figure.figsize']=[fig_width, fig_height]
plt.savefig('preds_actuals.png')
plt.show()

