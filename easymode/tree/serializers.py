"""
Contains an instance of Serializer and extends it to allow for recusive
serialization of django models with foreign keys.
"""
from StringIO import StringIO

from django.conf import settings
from django.core.serializers import xml_serializer

from easymode.tree.introspection import get_default_field_descriptors, \
    get_foreign_key_desciptors, get_generic_relation_descriptors
from easymode.utils.xmlutils import XmlPrinter


# startDocument must only be called once
# so override it
def startDocumentOnlyOnce(self):
    if hasattr(self, 'allready_called'):
        return
    self.allready_called = True
    XmlPrinter.startDocument(self)

XmlPrinter.startDocument = startDocumentOnlyOnce

class RecursiveXmlSerializer(xml_serializer.Serializer):
    """
    Serializes a queryset including related fields
    """
    def serialize(self, queryset, **options):
        """
        Serialize a queryset.
        THE OUTPUT OF THIS SERIALIZER IS NOT MEANT TO BE SERIALIZED BACK
        INTO THE DB.        
        """
        self.options = options

        self.stream = options.get("stream", StringIO())
        self.selected_fields = options.get("fields")
        self.use_natural_keys = options.get("use_natural_keys", True)
        
        self.xml = options.get("xml", None)
        self.root = (self.xml == None)
        
        self.start_serialization()
        for obj in queryset:
            self.start_object(obj)
            for field in obj._meta.local_fields:
                if field.serialize and getattr(field, 'include_in_xml', True):
                    if field.rel is None:
                        if self.selected_fields is None or field.attname in self.selected_fields:
                            self.handle_field(obj, field)
                    else:
                        if self.selected_fields is None or field.attname[:-3] in self.selected_fields:
                            self.handle_fk_field(obj, field)

            # recursively serialize all foreign key relations
            for (foreign_key_descriptor_name, foreign_key_descriptor ) in get_foreign_key_desciptors(obj):
                if foreign_key_descriptor.related.field.serialize:
                    bound_foreign_key_descriptor = foreign_key_descriptor.__get__(obj)
                    s = RecursiveXmlSerializer()                
                    s.serialize( bound_foreign_key_descriptor.all(), xml=self.xml, stream=self.stream)

            #recursively serialize all one to one relations
            # TODO: make this work for non abstract inheritance but without infinite recursion
            # for (one_to_one_descriptor_name, one_to_one_descriptor) in get_one_to_one_descriptors(obj):
            #     related_objects = []
            #     try:
            #         related_object = one_to_one_descriptor.__get__(obj)
            #         related_objects.append(related_object)
            #     except Exception as e:
            #         pass
            # 
            #     s = RecursiveXmlSerializer()                
            #     s.serialize( related_objects, xml=self.xml, stream=self.stream)

            # add generic relations
            for (generic_relation_descriptor_name, generic_relation_descriptor) in get_generic_relation_descriptors(obj):
                # generic relations always have serialize set to False so we always include them.
                bound_generic_relation_descriptor = generic_relation_descriptor.__get__(obj)
                s = RecursiveXmlSerializer()                
                s.serialize( bound_generic_relation_descriptor.all(), xml=self.xml, stream=self.stream)
                
            #serialize the default field descriptors:
            for (default_field_descriptor_name, default_field_descriptor) in get_default_field_descriptors(obj):
                if default_field_descriptor.serialize:
                    self.handle_field(obj, default_field_descriptor)
                
            for field in obj._meta.many_to_many:
                if field.serialize:
                    if self.selected_fields is None or field.attname in self.selected_fields:
                        self.handle_m2m_field(obj, field)
            self.end_object(obj)
        self.end_serialization()
        return self.getvalue()

    def start_serialization(self):
        """
        Start serialization -- open the XML document and the root element.
        """
        if (self.root):
            self.xml = XmlPrinter(self.stream, self.options.get("encoding", settings.DEFAULT_CHARSET))
            self.xml.startDocument()
            self.xml.startElement("django-objects", {"version" : "1.0"})


    def end_serialization(self):
        """
        End serialization -- end the document.
        """
        if (self.root):
            self.indent(0)
            self.xml.endElement("django-objects")
            self.xml.endDocument()


    def handle_field(self, obj, field):
        """
        Called to handle each field on an object (except for ForeignKeys and
        ManyToManyFields)
        """
        self.indent(2)

        fields_attrs = {
            "name" : field.name,
            "type" : field.get_internal_type()
        }
        # handle fields with a extra_attrs set as speciul
        if hasattr(field, 'extra_attrs'):
            if field.extra_attrs:
                fields_attrs.update(field.extra_attrs)
            fields_attrs['name'] = field.name.replace('_', '.')

        self.xml.startElement("field", fields_attrs)

        # Checks for a custom value serializer 
        if not hasattr(field, 'custom_value_serializer'):
            # Get a "string version" of the object's data.
            if getattr(obj, field.name) is not None:
                self.xml.characters(field.value_to_string(obj))
            else:
                self.xml.addQuickElement("None")
        else:
            field.custom_value_serializer(obj, self.xml)

        self.xml.endElement("field")