# qctab.py

"""
Created on 31/7/2018

@author: Iosif Spartalis

Quality Control tool for tabular data


"""
# TODO: Build unit tests

import argparse
import os
import logging
import datetime
import pandas as pd

__version__ = '0.0.2'
DIR_PATH = os.path.dirname(os.path.realpath(__file__))

# Create and configure logger
LOG_FORMAT = "%(levelname)s %(asctime)s - %(message)s"
logging.basicConfig(filename=os.path.join(DIR_PATH, 'lumperjack.log'),
                    level=logging.DEBUG,
                    format=LOG_FORMAT,
                    filemode='w')
LOGGER = logging.getLogger()


class Metadata(object):
    """Class for manupulating metadata files"""
    # TODO: implement class methods for loading  csv and json
    def __init__(self, dataframe, col_val, col_type):
        """col_val -> column with the variable names
           col_type -> column with the variable types
        """
        assert isinstance(dataframe, pd.core.frame.DataFrame)
        self.defined_columns = ['variable_name', 'type']

        if not all(column in dataframe.columns for column in [col_val, col_type]):
           raise Exception \
                    ("{0} or {1} is not found in the metadata".format(col_val,col_type))
        new_columns = dict(zip([col_val, col_type],
                               self.defined_columns))
        self.meta = dataframe.rename_axis(new_columns, axis=1)
        self.meta.set_index('variable_name', drop=False, inplace=True)

    @classmethod
    def from_csv(cls, filename, col_val, col_type, **kwargs):
        """Reads a metadata csv file"""
        data = pd.read_csv(filename, **kwargs)
        return cls(data, col_val, col_type)

class VariableStats(object):
    """Class for calculating statistics of a hospital tabular dataset.
    """
    _metadata = None
    # The metadata columns that are used in this class
    meta_columns = ['variable_name', 'type']

    # The dataframe with variable statistics will have these columns
    basic_columns = ['variable_name', 'type', 'type_estimated',
                     'category_levels', 'total_levels',
                     'unique', 'top', 'freq',
                     'count', 'not_null_%',
                     'mean', 'std', 'min', 'max',
                     '25%', '50%', '75%', '#_of_outliers',
                     'bottom_5_text_values', 'top_5_text_values',
                     'not_null_bins', 'comments']


    def __init__(self, dataset, metadata=None):
        """dataset -> pandas DataFrame with hospital data
           metadata -> pandas DataFrame with metadata about the variables
                       has to have a column 'type'
        """
        assert isinstance(dataset, pd.core.frame.DataFrame)
        self.data = dataset
        self.metadata = metadata
        self.vstats = self.create_emtpy_vstat_df(self.basic_columns)
        self._fill_vstats()

    @property
    def metadata(self):
        """Returns the metadata dataframe"""
        return self._metadata

    @metadata.setter
    def metadata(self, mdata):
        """Sets the metadata dataframe from a Metadata object"""
        if isinstance(mdata, Metadata):
            LOGGER.debug("Found metadata object")
            if isinstance(self._metadata, pd.core.frame.DataFrame):
                self._metadata.update(mdata.meta[self.meta_columns])
            else:
                self._metadata = mdata.meta[self.meta_columns]
                LOGGER.debug(self._metadata.columns)
        else:
            LOGGER.debug("not found metadata object")
            self._metadata = None

    def create_emtpy_vstat_df(self, columns):
        """Returns a Dataframe with empty rows and given columns.
        nrows = # of dataset variables
        ncolumns = # of given columns
        """
        new_df = pd.DataFrame(index=self.data.columns, columns=columns)
        # Fill the df with the variables names aka columns of the dataset csv
        new_df['variable_name'] = new_df.index
        return new_df

    def _fill_vstats(self):
        """Fill the vstats dataframe with statistics about dataset
        variables"""

        df1 = self.create_emtpy_vstat_df(self.basic_columns)

        # Calculate descriptive statistics for all types of the
        # dataset variables and store it to a dataframe.
        df_desc = self.data.describe(include='all').transpose()
        df1.update(df_desc)
        df_desc = None

        # Calculate the not null percentage per variable
        df1['not_null_%'] = df1['count']/len(self.data) * 100
        df1['not_null_%'] = df1['not_null_%'].apply(lambda x: round(x, 2))

        # Calculate the number of outliers per numerical variable
        df_outliers = self._calc_outliers(3)
        df1.update(df_outliers)
        df_outliers = None

        # Place the variables to buckets according to its
        # not null percentage
        # NOTE: the 100% bin is filled with values 99.99-100
        var_labels = ['#_0-19.99%', '#_20-39.99%', '#_40-59.99%',
                      '#_60-79.99%', '#_80-99.99%', '#_100%']
        var_bins = [0, 19.99, 39.99, 59.99, 79.99, 99.99, 100]
        df1['not_null_bins'] = pd.cut(df1['not_null_%'], bins=var_bins,
                                      labels=var_labels, include_lowest=True)

        # Check if exist the metadata dataframe
        # update the main dataframe
        # Get the variable names that are declared categorical
        # in the metadata
        if isinstance(self.metadata, pd.core.frame.DataFrame):
            df1.update(self.metadata)
            cat_criterion = df1['type'].map(lambda x: x == 'nominal')
            meta_categories = list(df1.loc[cat_criterion, 'variable_name'])
            df1.update(self._calc_categories(meta_categories))

        # Estimate the data types of the variables without using
        # the metadata csv
        df1.update(self._rough_estimate_types())

        # Get the top and bottom values of the text variables
        # (dates are considered as text too)
        text_criterion1 = df1['type_estimated'].map(lambda x: x == 'text')
        text_criterion2 = df1['type'].map(lambda x: x != 'nominal')
        text_variables = list(df1.loc[text_criterion1 & text_criterion2,
                                      'variable_name'])
        df1.update(self._calc_topstrings(text_variables, 5))

        self.vstats.update(df1)

    def _calc_categories(self, cat_variables):
        """ Returns the categories and the number of categories of the given
        nominal varables.
        """
        category_values = []
        total_categories = []
        for variable in cat_variables:
            # get all the values of the current variable and store them
            values_list = list(self.data[variable].value_counts().index)
            category_values.append(str(values_list).strip('[]'))
            # count and store them
            total_categories.append(len(values_list))
        result = pd.DataFrame({'variable_name': cat_variables,
                             'category_levels': category_values,
                             'total_levels': total_categories})
        result.set_index('variable_name', drop=False, inplace=True)
        return result

    def _calc_topstrings(self, text_variables, total):
        """Returns the total top and total bottom variable values
        in respect to their frequency.
        """
        top_values = []
        bottom_values = []
        for variable in text_variables:
            # get all the values of the current variable and store them
            values = self.data[variable].value_counts()
            top = list(values.head(total).index)
            bottom = list(values.tail(total).index)
            top_values.append(str(top).strip('[]'))
            bottom_values.append(str(bottom).strip('[]'))
        result = pd.DataFrame({'variable_name': text_variables,
                             'top_{0}_text_values'.format(total): top_values,
                             'bottom_{0}_text_values'.format(total): bottom_values})
        result.set_index('variable_name', drop=False, inplace=True)
        return result

    def _calc_outliers(self, times):
        """Calculates the # of outliers per numerical variable
        returns a df with a column '#_of_outliers' and as index
        is used the numerical variables names """
        numeric_variables = self.data.select_dtypes(include=['float64', 'int64']).columns
        df1 = pd.DataFrame(index=numeric_variables, columns=["#_of_outliers"])
        for variable in numeric_variables:
            df1.at[variable, "#_of_outliers"] = outliers(self.data[variable], times)
        return df1

    def _rough_estimate_types(self):
        """Estimates the data type of the dataset variables"""
        # TODO: make it more sofisticated
        # Find the numerical variables in the dataset and store them in a dataframe
        numeric_variables = self.data.select_dtypes(include=['float64','int64']).columns
        df_numeric = pd.DataFrame(index=numeric_variables, columns=['type_estimated'])
        df_numeric['type_estimated'] = 'numerical'
        # The rest variables in the dataset are object type
        other_variables = self.data.select_dtypes(exclude=['float64', 'int64']).columns
        df_other = pd.DataFrame(index=other_variables, columns=['type_estimated'])
        df_other['type_estimated'] = 'text'

        # return the concatenation of those dataframes
        df_result = pd.concat([df_numeric, df_other])
        return df_result

    def _make_readable_vstats(self):
        """Returns a variablestats df with more readable columns names."""
        new_columns = {"type": "type declared",
                       "category_levels": "list of category values",
                       "total_levels": "number of category values",
                       "unique": "count of unique values (for categorical variables)",
                       "top": "most frequent value (for categorical variables)",
                       "freq": ("number of occurrences for most frequent"
                                + " value (for catigorical values)"),
                       "count": "count of records filled in",
                       "not_null_%": "% of not null rows",
                       "25%": ("25% of records are below this value"
                               + "(limit value of the first quartile"),
                       "50%": "50% of records re below this value",
                       "75%": ("75% of records are below this value"
                               + "(limit value of the third quartile)"),
                       "#_of_outliers": "#_of_outliers(outside 3 std.dev)",
                       "bottom_5_text_values": "5 least frequent values",
                       "top_5_text_values": "5 most frequent values"}
        return self.vstats.rename(columns=new_columns)


class DatasetCsv(VariableStats):
    """This class is for producing a statistical report about
    a given csv dataset
    """

    def __init__(self, data, dname, metadata=None):
        """ data -> pandas dataframe
        dname -> a string with the name of dataset file
        hospital dataset csv file
        """
        # TODO: update the docstring
        # TODO: add exceptions
        # TODO: add outlier and total critirion to the arguments
        # TODO: impove the export_html method for prettier results
        # TODO: add export_pdf method

        # Read the dataset csv file without declared dtypes
        # This has the effect that the dates and categorical
        # variables will be represented as 'object' dtype
        super().__init__(data, metadata)
        self.id_column = self.data.columns[0]
        self.dataset_name = dname
        # TODO: change this part of documenation, replace dataframe with dict
        # Create a pandas dataframe attribute for dataset statistics
        # self.datasetstats
        self.dstats = {}
        self._initialize_dstats()
        # Calc dataset not null % categories
        self._calc_dstats_notnnullcat()

    def _initialize_dstats(self):
        """Initialize the dict dstats with the some statistics about the
            dataset
        """
        id_column = self.id_column
        self.dstats['name_of_file'] = self.dataset_name
        self.dstats['date_qc_ran'] = datetime.datetime.now()
        # TODO: correct the __version__
        self.dstats['qctool_version'] = __version__

        self.dstats['total_rows'] = self.data.shape[0]
        self.dstats['total_variables'] = self.data.shape[1]

        # rows_no_id
        criterion = self.data[id_column].map(lambda x: pd.isnull(x))
        # Find the number of rows with no patient id
        self.dstats['rows_no_id'] = self.data[criterion].shape[0]

        # rows_only_id
        # Find the number of rows with only patient id and no data at all
        dataset_columns = list(self.data.columns)  # get the columns names of the dataset
        dataset_columns.remove(id_column)  # remove the patient id column
        df_temp1 = self.data[dataset_columns].isnull()
        self.dstats['rows_only_id'] = sum(df_temp1.all(axis=1))
        df_temp1 = None

        # rows_complete
        # Find the number of rows with all the columns being filled
        df_temp1 = ~self.data.isnull()  # reverse the boolean values
        self.dstats['rows_complete'] = sum(df_temp1.all(axis=1))
        df_temp1 = None

        # '#_0-19.99%', '#_20-39.99%', '#_40-59.99%','#_60-79.99%'
        # '#_80-99.99%', '#_100%'
        d = {'#_0-19.99%': 0, '#_20-39.99%': 0, '#_40-59.99%': 0,
             '#_60-79.99%': 0, '#_80-99.99%': 0, '#_100%': 0}
        self.dstats.update(d)

    def _calc_dstats_notnnullcat(self):
        """Updates the dstats with the # of variables
        are in the 6 not null % categories
        """
        # '#_0-19.99%', '#_20-39.99%', '#_40-59.99%','#_60-79.99%'
        # '#_80-99.99%', '#_100%'
        # get the counts of variables not null categories
        notnullcat = self.vstats.loc[:, 'not_null_bins'].value_counts(dropna=False)
        # convert the Series item to df, transpose so categories become columns
        # and drop index
        notnullcat = notnullcat.to_frame().transpose().reset_index(drop=True)
        dict_notnull = pandas_2_dict(notnullcat)
        self.dstats.update(dict_notnull)

    def _dstat_2_df(self, readable=False):
        """Converts the dstat dictionary to pandas df"""
        dstats_df = pd.DataFrame(dict_4_pandas(self.dstats))
        # Rearrange the column order of the dataset
        ordered_columns = ['name_of_file', "qctool_version", "total_variables",
                           "total_rows", "rows_only_id", "rows_no_id",
                           "rows_complete", "#_100%", "#_80-99.99%",
                           "#_60-79.99%", "#_40-59.99%", "#_20-39.99%",
                           "#_0-19.99%"]
        dstats_df = dstats_df[ordered_columns]
        if readable:
            new_columns = {"rows_only_id": "rows with only id",
                       "rows_no_id": "rows with no id",
                       "rows_complete": "rows with all columns filled",
                 "#_0-19.99%": "number of variables with 0-19.99% records filled in",
                 "#_20-39.99%": "number of variables with 20-39.99% records filled in",
                 "#_40-59.99%": "number of variables with 40-59.99% records filled in",
                 "#_60-79.99%": "number of variables with 60-79.99% records filled in",
                 "#_80-99.99%": "number of variables with 80-99.99% records filled in",
                 "#_100%": "number of variables with 100% records filled in"}
            dstats_df.rename(columns=new_columns, inplace=True)
        return dstats_df

    def export_dstat_csv(self, filepath, need_readable=False):
        """Exports the datasetstats and variablestats dataframes to a csv.
        """
        datasetstats = self._dstat_2_df(need_readable)
        datasetstats.to_csv(exportfile_ds, index=False)
        # Export to csv with readable column names?

    def export_vstat_csv(self, filepath, need_readable=False):
        """Exports the variable statistics to a csv"""
        if need_readable:
            readable_df_vstats = self._make_readable_vstats()
            readable_df_vstats.drop(labels=['not_null_bins'],
                                    axis=1).to_csv(filepath,
                                                   index=False)
        else:
            self.vstats.drop(labels=['not_null_bins'],
                                    axis=1).to_csv(filepath,
                                                   index=False)

    def export_html(self):
        """Exports the datasetstats and variablestats dataframe to html.
        """
        pass


def outliers(numbers, times):
    """Returns the number of outliers of a given list of numbers.
    Outlier is consider the value which is outside (times * std deviations)
    w/r of the avarage value.
    numbers -> array or pandas Series
    times   -> how many times bigger from the std deviation will
               be the space which outside values would be
               considered as outliers.
    Returns -> an intenger """
    assert isinstance(numbers, pd.core.series.Series), 'numbers must be panda Series'
    assert isinstance(times, (int, float)), 'times must be a number'
    mean, std = numbers.mean(), numbers.std()
    # Define upper bound of the space of non-outliers
    upper = mean + times * std
    # Define the lower bound of the space of non-outliers
    lower = mean - times * std
    # Return how many values are not inside this space
    return len(numbers[(numbers < lower) | (numbers > upper)])


def dict_4_pandas(d):
    """Takes a dict {key : value} and returns dict {key : [value]}"""
    new_dict = {}
    for key in d.keys():
        new_dict[key] = [d[key]]
    return new_dict

def pandas_2_dict(df):
    """Takes a pd Dataframe and returns
    a dict {column : value} of the first row only"""
    new_dict = df.to_dict(orient='records')
    return new_dict[0]

if __name__ == '__main__':
    # Create a parser
    PARSER = argparse.ArgumentParser(description="A tool that provides a \
                                     statistical report about the \
                                     input csv file.")
    PARSER.add_argument("--input_csv", type=str,
                        help="dataset input csv")
    PARSER.add_argument("--meta_csv", type=str,
                        help="variables metadata csv")
    ARGS = PARSER.parse_args()
    METADATA = None
    # Get the filename and dataset name
    FILENAME = ARGS.input_csv
    DATASET_NAME = os.path.splitext(FILENAME)[0]
    # Get the path of the csv file
#    path = os.path.dirname(os.path.abspath(ARGS.input_csv))

    if ARGS.meta_csv:
        METADATA = Metadata.from_csv(ARGS.meta_csv, 'variable', 'type_d')
    else:
        METADATA = None
    DATA = pd.read_csv(ARGS.input_csv, index_col=None)
    testcsv = DatasetCsv(DATA, FILENAME, METADATA)
#    exportfile_ds = os.path.join(path, dataset_name
#                                 + '_dataset_report.csv')
    exportfile =  DATASET_NAME + '_report.csv'
    exportfile_ds = DATASET_NAME + '_dataset_report.csv'


    testcsv.export_dstat_csv(exportfile_ds, need_readable=True)
    testcsv.export_vstat_csv(exportfile, need_readable=True)
