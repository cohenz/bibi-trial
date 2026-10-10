/**
 * Editor script for trial-knowledge/source-citation. Rendering is server-side
 * (TK_Blocks), so the editor preview always matches the published output.
 */
import { registerBlockType } from '@wordpress/blocks';
import { InspectorControls, useBlockProps } from '@wordpress/block-editor';
import { PanelBody, TextControl } from '@wordpress/components';
import ServerSideRender from '@wordpress/server-side-render';
import { __ } from '@wordpress/i18n';
import metadata from './block.json';

registerBlockType(metadata.name, {
	edit({ attributes, setAttributes }) {
		const blockProps = useBlockProps();
		return (
			<div {...blockProps}>
				<InspectorControls>
					<PanelBody title={__('הגדרות', 'trial-knowledge')}>
						<TextControl __nextHasNoMarginBottom label={__('מזהה יחידת מקור (su_…)', 'trial-knowledge')} value={attributes.sourceUnitId} onChange={(v) => setAttributes({ sourceUnitId: v.trim() })} />
					</PanelBody>
				</InspectorControls>
				<ServerSideRender block={metadata.name} attributes={attributes} />
			</div>
		);
	},
	save: () => null,
});
