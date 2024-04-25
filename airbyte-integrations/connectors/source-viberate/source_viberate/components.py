#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#

from dataclasses import InitVar, dataclass
from typing import Any, Iterable, List, Mapping, Optional, Union
import json

from airbyte_cdk.sources.declarative.interpolation.interpolated_string import InterpolatedString
from airbyte_cdk.sources.declarative.requesters.request_option import RequestOption, RequestOptionType
from airbyte_cdk.sources.declarative.stream_slicers.stream_slicer import StreamSlicer
from airbyte_cdk.sources.declarative.types import Config, StreamSlice, StreamState

from google.cloud import bigquery
from google.oauth2 import service_account

@dataclass
class SpotifyPartitionRouter(StreamSlicer):
    """
    Partition router that iterates over the values of a list
    If values is a string, then evaluate it as literal and assert the resulting literal is a list

    Attributes:
        entity_name: Union[InterpolatedString, str]: The spotify entity, i.e. track, album, artist
        cursor_field (Union[InterpolatedString, str]): The name of the cursor field
        config (Config): The user-provided configuration as specified by the source's spec
        request_option (Optional[RequestOption]): The request option to configure the HTTP request
    """

    entity_name: Union[InterpolatedString, str]
    cursor_field: Union[InterpolatedString, str]
    config: Config
    parameters: InitVar[Mapping[str, Any]]
    request_option: Optional[RequestOption] = None

    def __post_init__(self, parameters: Mapping[str, Any]) -> None:
        self._cursor_field = (
            InterpolatedString(string=self.cursor_field, parameters=parameters) if isinstance(self.cursor_field, str) else self.cursor_field
        )

        self._cursor = None

    def get_request_params(
        self,
        stream_state: Optional[StreamState] = None,
        stream_slice: Optional[StreamSlice] = None,
        next_page_token: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        # Pass the stream_slice from the argument, not the cursor because the cursor is updated after processing the response
        return self._get_request_option(RequestOptionType.request_parameter, stream_slice)

    def get_request_headers(
        self,
        stream_state: Optional[StreamState] = None,
        stream_slice: Optional[StreamSlice] = None,
        next_page_token: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        # Pass the stream_slice from the argument, not the cursor because the cursor is updated after processing the response
        return self._get_request_option(RequestOptionType.header, stream_slice)

    def get_request_body_data(
        self,
        stream_state: Optional[StreamState] = None,
        stream_slice: Optional[StreamSlice] = None,
        next_page_token: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        # Pass the stream_slice from the argument, not the cursor because the cursor is updated after processing the response
        return self._get_request_option(RequestOptionType.body_data, stream_slice)

    def get_request_body_json(
        self,
        stream_state: Optional[StreamState] = None,
        stream_slice: Optional[StreamSlice] = None,
        next_page_token: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        # Pass the stream_slice from the argument, not the cursor because the cursor is updated after processing the response
        return self._get_request_option(RequestOptionType.body_json, stream_slice)

    def stream_slices(self) -> Iterable[StreamSlice]:
        json_acct_info = json.loads(self.config['gcp_credentials'])
        credentials = service_account.Credentials.from_service_account_info(json_acct_info)
        bq_client = bigquery.Client(credentials=credentials)
        query = f"""
            select      
                spotify_id
            from `hardy-force-319814.pirate_dbt_prod.artist_ops_spotify_links`
            where link_type = '{self.entity_name}'
        """

        values = (
            bq_client.query(query)
            .result()
            .to_dataframe()['spotify_id']
            .to_list()
        )

        return [StreamSlice(partition={self._cursor_field.eval(self.config): slice_value}, cursor_slice={}) for slice_value in values]

    def _get_request_option(self, request_option_type: RequestOptionType, stream_slice: Optional[StreamSlice]) -> Mapping[str, Any]:
        if self.request_option and self.request_option.inject_into == request_option_type and stream_slice:
            slice_value = stream_slice.get(self._cursor_field.eval(self.config))
            if slice_value:
                return {self.request_option.field_name.eval(self.config): slice_value}  # type: ignore # field_name is always casted to InterpolatedString
            else:
                return {}
        else:
            return {}
