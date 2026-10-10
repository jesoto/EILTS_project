import pytest
import streamlit as st


@pytest.fixture(autouse=True)
def _clear_streamlit_caches():
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()
