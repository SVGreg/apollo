# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Compatibility import for the standalone remote Apollo client.

The implementation lives in the zero-dependency ``apollo-client`` package.
Keeping this module lets existing full-runtime installations migrate without
maintaining a second client execution path.
"""

from apollo.runtime import ConcurrencyMode
from apollo_client import ApolloClient

__all__ = ["ApolloClient", "ConcurrencyMode"]
