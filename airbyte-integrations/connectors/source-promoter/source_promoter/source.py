#
# Copyright (c) 2021 Airbyte, Inc., all rights reserved.
#

import math
from abc import ABC
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Tuple

import requests
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http import HttpStream
from airbyte_cdk.sources.streams.http.auth import TokenAuthenticator
from airbyte_cdk.models import SyncMode

# Basic full refresh stream
class PromoterStream(HttpStream, ABC):
    url_base = "https://app.promoter.io/api/v2/"

    page_size = 100
    page = 1

    def backoff_time(self, response: requests.Response) -> Optional[int]:
        delay_time = response.headers.get("Retry-After")
        if delay_time:
            return int(delay_time)

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        response_size = len(response.json().get("results", []))
        if response_size == self.page_size:
            self.page += 1
            return {"page": self.page}

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None
    ) -> MutableMapping[str, Any]:
        params = {"page_size": self.page_size}
        if next_page_token:
            params.update(next_page_token)
        print(params)
        return params

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        response_json = response.json()
        yield from response_json.get("results", [])


class Feedback(PromoterStream):
    primary_key = "id"

    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "feedback"


# Basic incremental stream
class IncrementalPromoterStream(PromoterStream, ABC):
    # Stripe returns most recently created objects first, so we don't want to persist state until the entire stream has been read
    state_checkpoint_interval = math.inf

    def __init__(self, lookback_window_days: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.lookback_window_days = lookback_window_days

    @property
    def cursor_field(self) -> str:
        """
        Defining a cursor field indicates that a stream is incremental, so any incremental stream must extend this class
        and define a cursor field.
        """
        pass

    def get_updated_state(self, current_stream_state: MutableMapping[str, Any], latest_record: Mapping[str, Any]) -> Mapping[str, Any]:
        """
        Return the latest state by comparing the cursor value in the latest record with the stream's most recent state object
        and returning an updated state object.
        """
        return {self.cursor_field: max(latest_record.get(self.cursor_field), current_stream_state.get(self.cursor_field, 0))}

    def request_params(self, stream_state: Mapping[str, Any] = None, **kwargs):
        stream_state = stream_state or {}
        params = super().request_params(stream_state=stream_state, **kwargs)

        start_timestamp = self.get_start_timestamp(stream_state)
        if start_timestamp:
            params["created[gte]"] = start_timestamp
        return params

    def get_start_timestamp(self, stream_state) -> int:
        start_point = self.start_date
        if stream_state and self.cursor_field in stream_state:
            start_point = max(start_point, stream_state[self.cursor_field])

        if start_point and self.lookback_window_days:
            self.logger.info(f"Applying lookback window of {self.lookback_window_days} days to stream {self.name}")
            start_point = int(pendulum.from_timestamp(start_point).subtract(days=abs(self.lookback_window_days)).timestamp())

        return start_point



class Employees(IncrementalPromoterStream):
    """
    TODO: Change class name to match the table/data source this stream corresponds to.
    """

    # TODO: Fill in the cursor_field. Required.
    cursor_field = "start_date"

    # TODO: Fill in the primary key. Required. This is usually a unique field in the stream, like an ID or a timestamp.
    primary_key = "employee_id"

    def path(self, **kwargs) -> str:
        """
        TODO: Override this method to define the path this stream corresponds to. E.g. if the url is https://example-api.com/v1/employees then this should
        return "single". Required.
        """
        return "employees"

    def stream_slices(self, stream_state: Mapping[str, Any] = None, **kwargs) -> Iterable[Optional[Mapping[str, any]]]:
        """
        TODO: Optionally override this method to define this stream's slices. If slicing is not needed, delete this method.

        Slices control when state is saved. Specifically, state is saved after a slice has been fully read.
        This is useful if the API offers reads by groups or filters, and can be paired with the state object to make reads efficient. See the "concepts"
        section of the docs for more information.

        The function is called before reading any records in a stream. It returns an Iterable of dicts, each containing the
        necessary data to craft a request for a slice. The stream state is usually referenced to determine what slices need to be created.
        This means that data in a slice is usually closely related to a stream's cursor_field and stream_state.

        An HTTP request is made for each returned slice. The same slice can be accessed in the path, request_params and request_header functions to help
        craft that specific request.

        For example, if https://example-api.com/v1/employees offers a date query params that returns data for that particular day, one way to implement
        this would be to consult the stream state object for the last synced date, then return a slice containing each date from the last synced date
        till now. The request_params function would then grab the date from the stream_slice and make it part of the request by injecting it into
        the date query param.
        """
        raise NotImplementedError("Implement stream slices or delete this method!")


# Source
class SourcePromoter(AbstractSource):
    @staticmethod
    def _get_authenticator(config: dict) -> TokenAuthenticator:
        return TokenAuthenticator(token=config['api_key'], auth_method='Token')

    def check_connection(self, logger, config) -> Tuple[bool, any]:
        auth = self._get_authenticator(config)
        try:
            feedback_stream = Feedback(authenticator=auth)
            next(feedback_stream.read_records(sync_mode=SyncMode.full_refresh))
            return True, None
        except Exception as e:
            return False, e

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        args = {"authenticator": self._get_authenticator(config)}
        return [
            Feedback(**args),
        ]
