from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.http.response import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
import json
from rest_framework import mixins, viewsets
from rest_framework.authentication import TokenAuthentication, \
    SessionAuthentication

from common.views import JsonQueryFilterBackend, SimpleQueryFilterBackend, paginate_requested_list, renderError

from .models import Collection, Repository
from .serializers import CollectionSerializer, RepositorySerializer


@login_required(login_url='/login/')
def getRawCoverageSourceData(request, collectionid, path):
    collection = get_object_or_404(Collection, pk=collectionid)

    coverage = collection.subset(path)

    if not coverage:
        raise Http404("Path not found.")

    if "children" in coverage:
        # Viewing a directory, so we should remove detailed coverage
        # information before returning this data.
        Collection.strip(coverage)
    else:
        # This is a leaf, we need to add source code
        collection.annotateSource(path, coverage)

    data = { "path" : path, "coverage" : coverage }
    return HttpResponse(json.dumps(data), content_type='application/json')

@login_required(login_url='/login/')
def index(request):
    return redirect('covmanager:collections')

@login_required(login_url='/login/')
def repositories(request):
    repositories = Repository.objects.all()
    return render(request, 'repositories/index.html', { 'repositories' : repositories })

@login_required(login_url='/login/')
def collections(request):
    entries = Collection.objects.all().order_by('-id')
    return render(request, 'collections/index.html', { 'collections' : paginate_requested_list(request, entries) })

class CollectionViewSet(mixins.CreateModelMixin,
                        mixins.ListModelMixin,
                        mixins.RetrieveModelMixin,
                        viewsets.GenericViewSet):
    """
    API endpoint that allows adding/viewing Collections
    """
    authentication_classes = (TokenAuthentication,)
    queryset = Collection.objects.all()
    serializer_class = CollectionSerializer
    filter_backends = [JsonQueryFilterBackend]

class RepositoryViewSet(mixins.CreateModelMixin,
                        mixins.ListModelMixin,
                        mixins.RetrieveModelMixin,
                        viewsets.GenericViewSet):
    """
    API endpoint that allows viewing Repositories
    """
    authentication_classes = (TokenAuthentication,)
    queryset = Repository.objects.all()
    serializer_class = RepositorySerializer
    filter_backends = [JsonQueryFilterBackend]